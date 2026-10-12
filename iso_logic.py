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
