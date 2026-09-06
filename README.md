# Lufux

<img src="lufux.svg" align="right" width="180" alt="Lufux Logo">

**English | [Русский](README_ru.md)**

A minimalist, universal, and functional GUI tool to create bootable USB drives on Linux, supporting both ISOHybrid and Windows images. Built with Python, GTK4, and Libadwaita.

<p align="left">
  <a href="https://github.com/Advnirr/lufux/releases">
    <img src="https://img.shields.io/badge/release-v1.3.6--stable-007EC6?style=flat-square" alt="Release">
  </a>
  <a href="https://github.com/Advnirr/lufux/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/license-GPL--3.0-FF5722?style=flat-square" alt="License">
  </a>
</p>

---

## ⚙️ Features

* **Windows Support:** Automatically detects Windows ISOs and applies the correct partition scheme (GPT/FAT32 for UEFI, or MBR/NTFS for Legacy BIOS).
* **Large WIM Handling:** Automatically detects solid `.esd` archives and `.wim` files larger than 4GB, splitting or converting them on the fly to bypass FAT32 limitations.
* **Windows To Go:** Installs Windows onto the USB drive itself, so it boots as a full portable system rather than an installer. Writes a hand-built BCD store keyed to the drive's own GPT GUIDs, verified to reach OOBE from a real removable stick.
* **Edition Choice:** A multi-edition ISO gets a list, so Windows To Go deploys the edition you pick instead of whichever one happens to come first.
* **Drive Speed Check:** Measures sequential and 4 KB random writes before a Windows To Go deployment and warns you if the drive is too slow to run Windows from.
* **Linux / Isohybrid Support:** Uses direct bit-for-bit block copying via `dd` for guaranteed bootability of Linux distributions.
* **Native:** GTK4/Adwaita interface.

## 📦 Dependencies

To run Lufux, you need the following system packages:
`python-gobject`, `gtk4`, `libadwaita`, `wimlib` (for wimlib-imagex), `rsync`, `parted`, `polkit` (for pkexec), `dosfstools` (for mkfs.vfat), `ntfs-3g` (for mkfs.ntfs).

`udisks2` is optional. It is what lets Lufux read the edition list out of an ISO without asking for a password; without it, Windows To Go deploys the first edition in the image.

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

## ⚠️ Warnings

* **The selected drive is erased completely,** in every mode. Check the device name on the summary page before you start.
* **Wait for the Done button before pulling the drive out.** Lufux unmounts everything before it reports success. Closing the app mid-flash is safe too, the drive is simply left unwritten.
* **A long flash looks like a frozen window.** Only phase names reach the log, so the progress bar is the one thing that moves.
* **Windows To Go needs a fast drive.** Writing takes hours, and Windows then runs off that drive, so a cheap USB 2.0 stick is bad at both. Lufux measures the drive first and warns you if it will not keep up.
* **If Windows To Go bugchecks with INACCESSIBLE_BOOT_DEVICE (0x7B), try another USB port.** A good drive can fail on one controller and boot fine from a port on another. `lsusb -t` shows which bus the drive is on, `grep -H . /sys/bus/usb/devices/usb*/serial` shows which controller each bus belongs to.

## 💜 Support

If Lufux helped you write a bootable drive, you can support continued development directly:

**USDT** · TON network

```
UQDFela8stCZykNL2cLw2erPkzjAgSf-GLXoJuiTEmEckTNB
```

## License
This project is licensed under the GNU General Public License v3.0 (GPL-3.0). See the [LICENSE](LICENSE) file for details.
