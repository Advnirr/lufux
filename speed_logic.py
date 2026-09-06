#!/usr/bin/env python3
"""Measure how fast a drive really is, before Windows To Go is deployed onto it.

Windows To Go does not merely live on the drive, it *runs* from it: every
page-in, every registry write, every event-log line is a small synchronous
write. A stick that copies one big file at a respectable rate can still be
unusable that way, so the sequential number decides nothing on its own - the
4 KiB random write rate is what separates a working system from one that sits
at 100% disk usage with a response time measured in minutes.

Destructive: it writes to the raw device. The caller runs it only after the
user has agreed to erase the drive, and after wipefs, so a drive whose test is
refused is left plainly empty rather than subtly corrupted.

Usage:  speed_logic.py /dev/sdX
Prints: SPEEDTEST: <sequential MB/s> <random 4K writes per second>
"""

import mmap
import os
import random
import sys
import time

SEQ_CHUNK = 4 << 20          # one sequential write
SEQ_LIMIT_BYTES = 64 << 20   # stop early on a fast drive
SEQ_LIMIT_SECONDS = 6.0      # and on a slow one, before the user gives up
RAND_BLOCK = 4096
RAND_LIMIT_OPS = 256
RAND_LIMIT_SECONDS = 6.0


def _open_device(path):
    """O_DIRECT if the device takes it, buffered-but-synchronous otherwise.

    O_DIRECT is what keeps the page cache from reporting the host's RAM speed
    instead of the stick's. Not every device or filesystem accepts it, and a
    benchmark is never worth failing a flash over, so fall back rather than
    raise. O_DSYNC in both cases: without it a write returns as soon as the
    request is queued, which is exactly the latency being measured.
    """
    try:
        return os.open(path, os.O_WRONLY | os.O_DIRECT | os.O_DSYNC), True
    except OSError:
        return os.open(path, os.O_WRONLY | os.O_DSYNC), False


def _buffer(size):
    # O_DIRECT needs the buffer aligned to the logical block size; an anonymous
    # mmap is page-aligned, which is always enough. Random bytes, so a
    # controller that compresses on the fly cannot flatter itself with zeroes.
    buf = mmap.mmap(-1, size)
    buf.write(os.urandom(size))
    buf.seek(0)
    return buf


def measure(path):
    fd, direct = _open_device(path)
    try:
        size = os.lseek(fd, 0, os.SEEK_END)
        if size < SEQ_CHUNK * 2:
            raise ValueError("drive too small to measure")

        # --- sequential ---
        chunk = _buffer(SEQ_CHUNK)
        limit = min(SEQ_LIMIT_BYTES, size)
        os.lseek(fd, 0, os.SEEK_SET)
        written = 0
        start = time.monotonic()
        while written < limit and time.monotonic() - start < SEQ_LIMIT_SECONDS:
            written += os.write(fd, chunk)
        seq_elapsed = time.monotonic() - start
        chunk.close()

        # --- random 4 KiB ---
        block = _buffer(RAND_BLOCK)
        blocks = size // RAND_BLOCK
        ops = 0
        start = time.monotonic()
        while ops < RAND_LIMIT_OPS and time.monotonic() - start < RAND_LIMIT_SECONDS:
            os.lseek(fd, random.randrange(blocks) * RAND_BLOCK, os.SEEK_SET)  # nosec B311
            os.write(fd, block)
            ops += 1
        rand_elapsed = time.monotonic() - start
        block.close()

        if not direct:
            os.fsync(fd)
    finally:
        os.close(fd)

    if seq_elapsed <= 0 or rand_elapsed <= 0 or written == 0 or ops == 0:
        raise ValueError("no measurable I/O")

    return written / seq_elapsed / 1e6, ops / rand_elapsed


def main():
    if len(sys.argv) != 2:
        print("usage: speed_logic.py /dev/sdX", file=sys.stderr)
        return 2
    try:
        seq_mbps, rand_iops = measure(sys.argv[1])
    # a benchmark that cannot run must never be the reason a flash does not:
    # the caller treats no output as "unknown" and carries on
    except (OSError, ValueError) as e:  # noqa: BLE001
        print(f"speed test failed: {e}", file=sys.stderr)
        return 1
    print(f"SPEEDTEST: {seq_mbps:.1f} {rand_iops:.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
