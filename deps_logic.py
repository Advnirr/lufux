import os
import shutil

PKG_MAP = {
    "arch": {
        "wimlib-imagex": "wimlib",
        "rsync": "rsync",
        "parted": "parted",
        "pkexec": "polkit",
        "bsdtar": "libarchive",
        "mkfs.vfat": "dosfstools",
        "mkfs.ntfs": "ntfs-3g"
    },
    "debian": {
        "wimlib-imagex": "wimtools",
        "rsync": "rsync",
        "parted": "parted",
        "pkexec": "policykit-1",
        "bsdtar": "libarchive-tools",
        "mkfs.vfat": "dosfstools",
        "mkfs.ntfs": "ntfs-3g"
    },
    "fedora": {
        "wimlib-imagex": "wimlib-utils",
        "rsync": "rsync",
        "parted": "parted",
        "pkexec": "polkit",
        "bsdtar": "bsdtar",
        "mkfs.vfat": "dosfstools",
        "mkfs.ntfs": "ntfsprogs"
    }
}

# mkfs.*, parted and wipefs live in sbin, which is not on a normal user's PATH
# on Debian, so shutil.which alone reports them missing when they are installed
SEARCH_DIRS = ("/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin", "/usr/local/sbin")

def _have_cmd(name):
    if shutil.which(name):
        return True
    return any(os.access(os.path.join(d, name), os.X_OK) for d in SEARCH_DIRS)

def check_dependencies():
    # mkfs.vfat (GPT path) and mkfs.ntfs (MBR path) are called by the Windows
    # script after the drive is already wiped, so they must be caught up front
    required_cmds = ["wimlib-imagex", "rsync", "parted", "pkexec", "bsdtar",
                     "mkfs.vfat", "mkfs.ntfs"]
    return [cmd for cmd in required_cmds if not _have_cmd(cmd)]

def get_distro_info():
    distro_id = "unknown"
    distro_name = "Unknown Linux"
    
    if os.path.exists("/etc/os-release"):
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("ID="):
                    distro_id = line.strip().split("=")[1].strip('"')
                elif line.startswith("ID_LIKE="):
                    like = line.strip().split("=")[1].strip('"')
                    if "arch" in like:
                        distro_id = "arch"
                    elif "debian" in like or "ubuntu" in like:
                        distro_id = "debian"
                    elif "fedora" in like or "rhel" in like:
                        distro_id = "fedora"
                elif line.startswith("PRETTY_NAME="):
                    distro_name = line.strip().split("=")[1].strip('"')

    base = "unknown"
    if distro_id in ["arch", "cachyos", "manjaro", "endeavouros"] or os.path.exists("/etc/arch-release"):
        base = "arch"
    elif distro_id in ["debian", "ubuntu", "linuxmint", "pop"] or os.path.exists("/etc/debian_version"):
        base = "debian"
    elif distro_id in ["fedora"] or os.path.exists("/etc/fedora-release"):
        base = "fedora"

    return base, distro_name

def get_install_cmd(missing_cmds):
    # list of argv lists (no shell), so package names can't be injected
    base, _ = get_distro_info()
    if base == "unknown" or "pkexec" in missing_cmds:
        return None

    packages = sorted({PKG_MAP[base][cmd] for cmd in missing_cmds if cmd in PKG_MAP[base]})
    if not packages:
        return None

    if base == "arch":
        return [["pkexec", "pacman", "-S", "--noconfirm", *packages]]
    elif base == "debian":
        return [
            ["pkexec", "apt-get", "update"],
            ["pkexec", "apt-get", "install", "-y", *packages],
        ]
    elif base == "fedora":
        return [["pkexec", "dnf", "install", "-y", *packages]]

    return None
