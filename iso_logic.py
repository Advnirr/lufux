"""What system an ISO holds, from its volume label and file name."""
import os
import re

# the ISO9660 primary volume descriptor: sector 16, label at byte 40
PVD_OFFSET = 16 * 2048

# (pattern, name, icon id, colour); first match wins, so flavours go first
KNOWN = [
    (r"kubuntu", "Kubuntu", "kubuntu", "#0079c1"),
    (r"xubuntu", "Xubuntu", "xubuntu", "#2b5fab"),
    (r"lubuntu", "Lubuntu", "lubuntu", "#0068c8"),
    (r"ubuntu", "Ubuntu", "ubuntu", "#e95420"),
    (r"cachyos", "CachyOS", "cachyos", "#1dc7b5"),
    (r"endeavouros", "EndeavourOS", "endeavouros", "#7f3fbf"),
    (r"manjaro", "Manjaro", "manjaro", "#35bf5c"),
    (r"garuda", "Garuda Linux", "garuda", "#a23be9"),
    (r"(^|[^a-z])arch", "Arch Linux", "archlinux", "#1793d1"),
    (r"fedora", "Fedora", "fedora", "#51a2da"),
    (r"debian", "Debian", "debian", "#a80030"),
    (r"mint", "Linux Mint", "linuxmint", "#87cf3e"),
    (r"pop[-_ ]?os", "Pop!_OS", "pop-os", "#48b9c7"),
    (r"opensuse|suse", "openSUSE", "opensuse", "#73ba25"),
    (r"alpine", "Alpine Linux", "alpine", "#0d597f"),
    (r"nixos", "NixOS", "nixos", "#5277c3"),
    (r"kali", "Kali Linux", "kali", "#367bf0"),
    (r"elementary", "elementary OS", "elementary", "#64baff"),
    (r"zorin", "Zorin OS", "zorin", "#15a6f0"),
    (r"gentoo", "Gentoo", "gentoo", "#54487a"),
    (r"void", "Void Linux", "void", "#478061"),
    (r"rocky", "Rocky Linux", "rocky", "#10b981"),
    (r"alma", "AlmaLinux", "almalinux", "#0f4266"),
    (r"centos", "CentOS", "centos", "#932279"),
    (r"tails", "Tails", "tails", "#56347c"),
    (r"proxmox", "Proxmox", "proxmox", "#e57000"),
]
WINDOWS = ("Windows", "windows", "#0078d4")
UNKNOWN_COLOR = "#77767b"


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


def identify(label, filename, windows=False):
    """(name, icon id, colour) for the system in the image.

    icon id is None when the system is not known; name then is the label.
    """
    if windows:
        return WINDOWS
    text = f"{label} {filename}".lower()
    for pattern, name, icon, color in KNOWN:
        if re.search(pattern, text):
            version = re.search(r"\d+(?:\.\d+)+", text)
            return (f"{name} {version.group()}" if version else name), icon, color
    name = label or os.path.splitext(filename)[0]
    return name, None, UNKNOWN_COLOR


def windows_name(editions):
    """"Windows 11" out of the edition names, plain "Windows" if none says."""
    for _, name, _ in editions:
        match = re.search(r"Windows \d+", name)
        if match:
            return match.group()
    return "Windows"


def badge_svg(name, color):
    """A circle in the system's colour with the first letter of its name."""
    letter = next((c for c in name if c.isalnum()), "?").upper()
    # drawn at 256 for HiDPI, shown at 128
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 128 128">'
        f'<circle cx="64" cy="64" r="64" fill="{color}"/>'
        '<text x="64" y="64" dy=".35em" text-anchor="middle" font-family="sans-serif" '
        f'font-weight="bold" font-size="64" fill="#fff">{letter}</text></svg>'
    ).encode()
