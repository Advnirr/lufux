"""Isohybrid images, written block for block to an fd udisks opens."""
import fcntl
import mmap
import os

from udisks_logic import bus, open_device, resolve, unmount_all

CHUNK = 4 << 20
# what wipefs used to clear: the backup GPT of the drive's old layout
TAIL = 1 << 20


def get_locale_dict():
    lang = os.environ.get('LANG', '')
    if lang.startswith('ru'):
        return {
            "unmount": "Отмонтирование...",
            "copy": "Копирование образа...",
            "sync": "Синхронизация ввода-вывода (sync)...",
            "verify": "Проверка записи...",
            "mismatch": "Образ записан некорректно",
        }
    return {
        "unmount": "Unmounting...",
        "copy": "Copying image...",
        "sync": "Syncing I/O (sync)...",
        "verify": "Verifying...",
        "mismatch": "The image was not written correctly",
    }


def copy_image(iso, fd, progress, stopped):
    """Copy iso onto fd. False if stopped() said to stop part way."""
    size = os.fstat(fd).st_size or os.lseek(fd, 0, os.SEEK_END)
    total = os.path.getsize(iso)
    if size > total + TAIL:
        os.pwrite(fd, bytes(TAIL), size - TAIL)
    os.lseek(fd, 0, os.SEEK_SET)
    done = 0
    with open(iso, "rb") as src:
        while chunk := src.read(CHUNK):
            if stopped():
                return False
            view = memoryview(chunk)
            while view:
                view = view[os.write(fd, view):]
            done += len(chunk)
            progress(done, total)
    return True


class Mismatch(OSError):
    """What was read back differs from the image."""


def verify_image(iso, fd, progress, stopped):
    """Read fd back and compare with iso. False if stopped part way."""
    # past the page cache, or this compares the image with itself
    try:
        fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_DIRECT)
    except OSError:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    total = os.path.getsize(iso)
    # O_DIRECT needs an aligned buffer, and mmap memory is page aligned
    buf = mmap.mmap(-1, CHUNK)
    done = 0
    with open(iso, "rb") as src:
        while chunk := src.read(CHUNK):
            if stopped():
                return False
            got = 0
            while got < len(chunk):
                n = os.preadv(fd, [memoryview(buf)[got:]], done + got)
                if n == 0:
                    break
                got += n
            if got < len(chunk) or buf[:len(chunk)] != chunk:
                raise Mismatch(get_locale_dict()["mismatch"])
            done += len(chunk)
            progress(done, total)
    return True


def write_image(iso, dev, status, progress, stopped, verify=False):
    """Write iso onto dev, read it back if verify. False if stopped part way.

    progress(done, total) counts bytes, from zero again for the read back.
    Raises GLib.Error for anything udisks refuses, OSError for a failed write
    and Mismatch for a failed check.
    """
    T = get_locale_dict()
    conn = bus()
    path = resolve(conn, dev)

    status(T["unmount"])
    unmount_all(conn, path)

    # O_SYNC: otherwise the copy fills the page cache in a second and the
    # whole write happens during fsync, with the bar already at 100%
    fd = open_device(conn, path, "rw" if verify else "w", os.O_SYNC)
    try:
        status(T["copy"])
        if not copy_image(iso, fd, progress, stopped):
            return False
        status(T["sync"])
        os.fsync(fd)
        if verify:
            status(T["verify"])
            if not verify_image(iso, fd, progress, stopped):
                return False
    finally:
        os.close(fd)
    return True
