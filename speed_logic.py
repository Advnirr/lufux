"""Measure how fast a drive really is, before Windows To Go is deployed onto it.

Windows To Go does not merely live on the drive, it runs from it: every
page-in, every registry write, every event-log line is a small synchronous
write. A stick that copies one big file at a good rate can still be unusable
that way, so the 4 KiB random write rate is the number that decides.

Destructive: it writes to the raw device. The caller runs it only after the
user has agreed to erase the drive, and after wiping it.
"""

import mmap
import os
import random
import time

SEQ_CHUNK = 4 << 20          # one sequential write
SEQ_LIMIT_BYTES = 64 << 20   # stop early on a fast drive
SEQ_LIMIT_SECONDS = 6.0      # and on a slow one, before the user gives up
RAND_BLOCK = 4096
RAND_LIMIT_OPS = 256
RAND_LIMIT_SECONDS = 6.0


def _buffer(size):
    # O_DIRECT needs the buffer aligned to the logical block size; an anonymous
    # mmap is page-aligned, which is always enough. Random bytes, so a
    # controller that compresses on the fly cannot flatter itself with zeroes.
    buf = mmap.mmap(-1, size)
    buf.write(os.urandom(size))
    buf.seek(0)
    return buf


def measure_fd(fd, direct):
    """(sequential MB/s, random 4 KiB writes/s) on an fd opened for writing.

    direct: whether the fd has O_DIRECT. Without it the page cache would
    report the host's RAM speed, so the caller opens it with O_SYNC too.
    """
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

    if seq_elapsed <= 0 or rand_elapsed <= 0 or written == 0 or ops == 0:
        raise ValueError("no measurable I/O")

    return written / seq_elapsed / 1e6, ops / rand_elapsed

