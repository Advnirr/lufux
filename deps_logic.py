import os
import shutil

# a value is one package, or a tuple where a distro splits the tool up
PKG_MAP = {
    "arch": {
        "wimlib-imagex": "wimlib",
        "mkfs.vfat": "dosfstools",
        "mkfs.ntfs": "ntfs-3g",
        "grub-mkimage": "grub"
    },
    "debian": {
        "wimlib-imagex": "wimtools",
        "mkfs.vfat": "dosfstools",
        "mkfs.ntfs": "ntfs-3g",
        # grub-mkimage is in grub-common, the BIOS modules in grub-pc-bin;
        # neither installs a bootloader onto this machine, unlike grub-pc
        "grub-mkimage": ("grub-common", "grub-pc-bin")
    },
    "fedora": {
        "wimlib-imagex": "wimlib-utils",
        "mkfs.vfat": "dosfstools",
        "mkfs.ntfs": "ntfsprogs",
        "grub-mkimage": ("grub2-tools", "grub2-pc-modules")
    }
}

# mkfs.* live in sbin, which is not on a normal user's PATH on Debian
SEARCH_DIRS = ("/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin", "/usr/local/sbin")

# grub-mkimage alone is not enough: a UEFI-only GRUB install has the command
# but not the i386-pc modules, and it would fail only after the drive is wiped.
# /app is the Flatpak's own GRUB.
GRUB_BIOS_MODULES = ("/usr/lib/grub/i386-pc/ntldr.mod", "/app/lib/grub/i386-pc/ntldr.mod")

def _have_cmd(name):
    if shutil.which(name):
        return True
    return any(os.access(os.path.join(d, name), os.X_OK) for d in SEARCH_DIRS)

def _have_bios_grub():
    return ((_have_cmd("grub-mkimage") or _have_cmd("grub2-mkimage"))
            and any(os.path.isfile(m) for m in GRUB_BIOS_MODULES))

def check_dependencies(windows=True, bios_boot=False):
    """Tools of ours the mode needs. mkfs is udisks' business, asked separately."""
    # the dd path goes through udisks and runs nothing of ours
    if not windows:
        return []
    # MBR media needs GRUB's images, the rest wimlib
    if bios_boot:
        return [] if _have_bios_grub() else ["grub-mkimage"]
    return [] if _have_cmd("wimlib-imagex") else ["wimlib-imagex"]

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
    if base == "unknown":
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
