import os
import shutil

# a value is one package, or a tuple where a distro splits the tool up
PKG_MAP = {
    "arch": {
        "wimlib-imagex": "wimlib",
        "rsync": "rsync",
        "parted": "parted",
        "pkexec": "polkit",
        "mkfs.vfat": "dosfstools",
        "mkfs.ntfs": "ntfs-3g",
        "grub-install": "grub"
    },
    "debian": {
        "wimlib-imagex": "wimtools",
        "rsync": "rsync",
        "parted": "parted",
        "pkexec": "policykit-1",
        "mkfs.vfat": "dosfstools",
        "mkfs.ntfs": "ntfs-3g",
        # grub-install is in grub2-common, the BIOS modules in grub-pc-bin;
        # neither installs a bootloader onto this machine, unlike grub-pc
        "grub-install": ("grub2-common", "grub-pc-bin")
    },
    "fedora": {
        "wimlib-imagex": "wimlib-utils",
        "rsync": "rsync",
        "parted": "parted",
        "pkexec": "polkit",
        "mkfs.vfat": "dosfstools",
        "mkfs.ntfs": "ntfsprogs",
        "grub-install": ("grub2-tools", "grub2-pc-modules")
    }
}

# mkfs.*, parted and wipefs live in sbin, which is not on a normal user's PATH
# on Debian, so shutil.which alone reports them missing when they are installed
SEARCH_DIRS = ("/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin", "/usr/local/sbin")

# grub-install alone is not enough: a UEFI-only GRUB install has the command
# but not the i386-pc modules, and it would fail only after the drive is wiped
GRUB_BIOS_MODULE = "/usr/lib/grub/i386-pc/ntldr.mod"

def _have_cmd(name):
    if shutil.which(name):
        return True
    return any(os.access(os.path.join(d, name), os.X_OK) for d in SEARCH_DIRS)

def _have_bios_grub():
    return ((_have_cmd("grub-install") or _have_cmd("grub2-install"))
            and os.path.isfile(GRUB_BIOS_MODULE))

def check_dependencies(bios_boot=False):
    # mkfs.vfat (GPT path) and mkfs.ntfs (MBR path) are called by the Windows
    # script after the drive is already wiped, so they must be caught up front
    required_cmds = ["wimlib-imagex", "rsync", "parted", "pkexec",
                     "mkfs.vfat", "mkfs.ntfs"]
    missing = [cmd for cmd in required_cmds if not _have_cmd(cmd)]
    # only MBR media boots through GRUB; nobody else should have to install it
    if bios_boot and not _have_bios_grub():
        missing.append("grub-install")
    return missing

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

    packages = set()
    for cmd in missing_cmds:
        pkg = PKG_MAP[base].get(cmd)
        if pkg:
            packages.update((pkg,) if isinstance(pkg, str) else pkg)
    packages = sorted(packages)
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
