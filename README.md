# Lufux

<img src="lufux.svg" align="right" width="180" alt="Lufux Logo">

**English | [Русский](README_ru.md)**

A simple GUI tool for making bootable USB drives on Linux: ISOHybrid images, Windows installers and Windows To Go. Built with Python, GTK4 and Libadwaita.

<p align="left">
  <a href="https://github.com/Advnirr/lufux/releases">
    <img src="https://img.shields.io/badge/release-v1.3.8--stable-007EC6?style=flat-square" alt="Release">
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
`python-gobject`, `gtk4`, `libadwaita`, `wimlib` (for wimlib-imagex), `rsync`, `parted`, `polkit` (for pkexec), `dosfstools` (for mkfs.vfat), `ntfs-3g` (for mkfs.ntfs), and `grub` for MBR/Legacy BIOS media only (`grub2-common` + `grub-pc-bin` on Debian/Ubuntu, `grub2-tools` + `grub2-pc-modules` on Fedora).

`udisks2` is optional. With it, Lufux reads the edition list from an ISO without asking for a password. Without it, Windows To Go installs the first edition in the image.

## 🚀 Installation

### Arch Linux / CachyOS (Recommended)

**Installation via AUR Helper**

The package is available on the Arch User Repository, so you can install it using Yay:
```bash
yay -S lufux-git
```

**Installation via PKGBUILD**

On Arch and Arch-based distributions you can build the package from the `PKGBUILD`:
```bash
git clone https://github.com/Advnirr/lufux.git
cd lufux
makepkg -si
```

### Debian / Ubuntu

Download `lufux_<version>_all.deb` from [Releases](https://github.com/Advnirr/lufux/releases) and install it:
```bash
sudo apt install ./lufux_*_all.deb
```
Works on Debian 13 and Ubuntu 24.04 or newer.

### Fedora

Download the `.rpm` from [Releases](https://github.com/Advnirr/lufux/releases) and install it:
```bash
sudo dnf install ./lufux-*.noarch.rpm
```

You can also build both packages with `tools/build-packages.sh`. It needs `dpkg-deb` and `rpmbuild` and puts the files in `dist/`.

### Manual Run (Any Distro)
You can run Lufux directly from the source code without installing it system-wide:
```bash
git clone https://github.com/Advnirr/lufux.git
cd lufux
python3 main.py
```
Install the dependencies listed above first.

## 🧪 Tests

```bash
python3 -m unittest discover -s tests
```

They cover what can be checked without a drive: the BCD store Lufux builds,
reading GPT GUIDs, the capacity check, dependency detection and the speed test.
They never touch a real device and do not need root.

## ⚠️ Warnings

* **The selected drive is erased completely,** in every mode. Check the device name on the summary page before you start.
* **NVMe drives are not listed.** This also hides Thunderbolt / USB4 enclosures, which connect the SSD over PCIe instead of USB. A normal USB-C enclosure works: `lsblk -o NAME,TRAN` shows `usb` for it. The filter keeps the internal system drive out of the list, and Lufux cannot tell the two apart yet. Fixing this needs someone with that hardware to help test.
* **Wait for the Done button before pulling the drive out.** Lufux unmounts everything before it reports success. Closing the app during a flash is also safe. The drive is just left unwritten.
* **During a long flash the window may look frozen.** Only stage names go to the log, so the progress bar is the only thing that moves.
* **Windows To Go needs a fast drive.** Writing takes hours, and then Windows runs from that drive. A cheap USB 2.0 stick is bad at both. Lufux tests the drive first and warns you if it is too slow.
* **If Windows To Go crashes with INACCESSIBLE_BOOT_DEVICE (0x7B), try another USB port.** A working drive can fail on one USB controller and boot fine on another. `lsusb -t` shows which bus the drive is on, and `grep -H . /sys/bus/usb/devices/usb*/serial` shows which controller each bus belongs to.

## 💜 Support

If Lufux helped you, you can support development:

**USDT** · TON network

```
UQDFela8stCZykNL2cLw2erPkzjAgSf-GLXoJuiTEmEckTNB
```

## License
This project is licensed under the GNU General Public License v3.0 (GPL-3.0). See the [LICENSE](LICENSE) file for details.
