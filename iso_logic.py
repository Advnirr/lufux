"""What system an ISO holds, from its volume label and file name."""
import os
import re

# the ISO9660 primary volume descriptor: sector 16, label at byte 40
PVD_OFFSET = 16 * 2048

# (pattern, name); first match wins, so flavours go first
KNOWN = [
    (r"kubuntu", "Kubuntu"),
    (r"xubuntu", "Xubuntu"),
    (r"lubuntu", "Lubuntu"),
    (r"ubuntu", "Ubuntu"),
    (r"cachyos", "CachyOS"),
    (r"endeavouros", "EndeavourOS"),
    (r"manjaro", "Manjaro"),
    (r"garuda", "Garuda Linux"),
    (r"(^|[^a-z])arch", "Arch Linux"),
    (r"fedora", "Fedora"),
    (r"debian", "Debian"),
    (r"mint", "Linux Mint"),
    (r"pop[-_ ]?os", "Pop!_OS"),
    (r"opensuse|suse", "openSUSE"),
    (r"alpine", "Alpine Linux"),
    (r"nixos", "NixOS"),
    (r"kali", "Kali Linux"),
    (r"elementary", "elementary OS"),
    (r"zorin", "Zorin OS"),
    (r"gentoo", "Gentoo"),
    (r"void", "Void Linux"),
    (r"rocky", "Rocky Linux"),
    (r"alma", "AlmaLinux"),
    (r"centos", "CentOS"),
    (r"tails", "Tails"),
    (r"proxmox", "Proxmox"),
]


def volume_label(path):
    """The ISO9660 volume label, "" when there is none."""
    try:
        with open(path, "rb") as f:
            f.seek(PVD_OFFSET)
            pvd = f.read(72)
    except OSError:
        return ""
    if pvd[1:6] != b"CD001":
        return ""
    return pvd[40:72].decode("ascii", "replace").strip()


def identify(label, filename):
    """The system's name, with its version when the label or file name has one.

    An unknown system is named by its label, or its file name without one.
    """
    text = f"{label} {filename}".lower()
    for pattern, name in KNOWN:
        if re.search(pattern, text):
            version = re.search(r"\d+(?:\.\d+)+", text)
            return f"{name} {version.group()}" if version else name
    return label or os.path.splitext(filename)[0]


def windows_name(editions):
    """"Windows 11" out of the edition names, plain "Windows" if none says."""
    for _, name, _ in editions:
        match = re.search(r"Windows \d+", name)
        if match:
            return match.group()
    return "Windows"


# A current Windows ISO keeps its real tree in UDF and leaves only a README on
# the ISO9660 side, and libarchive cannot read UDF, so the raw image is
# searched. ISO9660 holds names as plain bytes, UDF as UTF-16BE, one path
# component per record, so the markers are single components.
ISO_WINDOWS = ("install.wim", "install.esd", "boot.wim", "bootmgr.efi")
ISO_LINUX = ("isolinux", "casper", "vmlinuz", "initrd.img", "grub.cfg")
# names live in the volume metadata near the front (630 KB in on the ISO this
# was built against); this bound is what an unrecognised image costs
ISO_SCAN = 64 << 20
ISO_CHUNK = 4 << 20


def _views(buf):
    """The chunk as lowercased text in each encoding a name can be in.

    UTF-16BE at both alignments: records need not start on an even offset.
    """
    yield buf.decode("latin-1").lower()
    for start in (0, 1):
        body = buf[start:]
        yield body[:len(body) & ~1].decode("utf-16-be", "ignore").lower()


def iso_kind(path):
    """0 for Windows, 1 for Linux, 2 for anything else, in one pass.

    A Windows marker anywhere wins over a Linux one.
    """
    linux = False
    try:
        with open(path, "rb") as f:
            carry = b""
            read = 0
            while read < ISO_SCAN:
                buf = f.read(ISO_CHUNK)
                if not buf:
                    break
                read += len(buf)
                window = carry + buf
                for text in _views(window):
                    if any(m in text for m in ISO_WINDOWS):
                        return 0
                    linux = linux or any(m in text for m in ISO_LINUX)
                # a name can straddle two chunks
                carry = window[-64:]
    except OSError:
        pass
    return 1 if linux else 2
