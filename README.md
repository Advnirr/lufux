# Lufux

<img src="lufux.svg" align="right" width="180" alt="Lufux Logo">

**English | [Русский](README_ru.md)**

A minimalist, universal, and functional GUI tool to create bootable USB drives on Linux, supporting both ISOHybrid and Windows images. Built with Python, GTK4, and Libadwaita.

<p align="left">
  <a href="https://github.com/Advnirr/lufux/releases">
    <img src="https://img.shields.io/badge/release-v1.2.0--stable-007EC6?style=flat-square" alt="Release">
  </a>
  <a href="https://github.com/Advnirr/lufux/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/license-GPL--3.0-FF5722?style=flat-square" alt="License">
  </a>
</p>

---

## ⚙️ Features

* **Windows Support:** Automatically detects Windows ISOs and applies the correct partition scheme (GPT/FAT32 for UEFI, or MBR/NTFS for Legacy BIOS).
* **Large WIM Handling:** Automatically detects solid `.esd` archives and `.wim` files larger than 4GB, splitting or converting them on the fly to bypass FAT32 limitations.
* **Linux / Isohybrid Support:** Uses direct bit-for-bit block copying via `dd` for guaranteed bootability of Linux distributions.
* **Native:** GTK4/Adwaita interface.

## 📦 Dependencies

To run Lufux, you need the following system packages:
`python-gobject`, `gtk4`, `libadwaita`, `wimlib` (for wimlib-imagex), `rsync`, `parted`, `polkit` (for pkexec), `libarchive` (for bsdtar).

## 🚀 Installation

### Arch Linux / CachyOS (Recommended)

**Installation via AUR Helper**

The package is available on the Arch User Repository, so you can install it using Yay:
```bash
yay -S lufux-git
```

**Installation via PKGBUILD**

Since Lufux provides a native `PKGBUILD`, installation on Arch-based distributions is straightforward:
```bash
git clone https://github.com/Advnirr/lufux.git
cd lufux
makepkg -si
```

### Manual Run (Any Distro)
You can run Lufux directly from the source code without installing it system-wide:
```bash
git clone https://github.com/Advnirr/lufux.git
cd lufux
python main.py
```
Note: Make sure you have the required system dependencies installed.

## License
This project is licensed under the GNU General Public License v3.0 (GPL-3.0). See the [LICENSE](LICENSE) file for details.
