pkgname=lufux-git
pkgver=1.4.1
pkgrel=1
pkgdesc="Create bootable USB drives on Linux, including Windows To Go"
arch=('any')
url="https://github.com/Advnirr/lufux"
license=('GPL3')
depends=('python-gobject' 'gtk4' 'libadwaita' 'wimlib' 'dosfstools' 'ntfs-3g' 'udisks2')
optdepends=('grub: boot MBR/NTFS Windows media on Legacy BIOS')
makedepends=('git')
source=("main.py" "windows_logic.py" "windows_togo_logic.py" "bcd_logic.py" "speed_logic.py" "universal_logic.py" "deps_logic.py" "iso_logic.py" "udisks_logic.py" "io.github.Advnirr.Lufux.desktop" "io.github.Advnirr.Lufux.metainfo.xml" "lufux.svg")
sha256sums=('9080fd708355ab400c4ccac9c838cecca8657ff7f30c2ac8b9c019f05b2a5b2b'
            '54e7a4c483aaf9b1102e65080883e44a4ddb38d83ccbb22934b8e0e3936be0b9'
            '6b37c6e0633577dbb9bc044e74d54827f096b6f9b8f7f682fd7470b2d9eb011c'
            '3fcc097c0baa6c786b5903b64789e1027a74efa4da4f78c414dc414694945c16'
            '9a34b9b3fbe9211b3c28ce862885a2a085f6b1e5b897b85c881989f80b37d69b'
            '5ede5b95a37da597fd20bca7166c4c0b2dc50542cb857d29b0c2968cea6d6d33'
            '9631a831a55fb15678bf41df26a841a22c410cbf108c6ab8bf918276461a753b'
            '72806e5c7469f0e391a0bbda45de93b07682f47895e150bcde9ab8fa1b3936f0'
            '77b655a331f28f68128fbd123657c4e58f3fb8cc2a1c310030a6b90c8d73ce52'
            '34bf2767d1e54db44d2e76bd13459fb70f744ed03bd4a0224af12f12f5aa1281'
            'c96431dddcacbe85108ea5e86ab46ed06f46f2fe3c4cb546816fcb465207580c'
            '706e7d7c0ea396617b8cb9f15890cb616ceafab98237d7296c5b3c6aaba3fb2e')

package() {
    install -d "${pkgdir}/usr/share/lufux"

    install -Dm755 "${srcdir}/main.py" "${pkgdir}/usr/share/lufux/main.py"
    install -Dm644 "${srcdir}/windows_logic.py" "${pkgdir}/usr/share/lufux/windows_logic.py"
    install -Dm644 "${srcdir}/windows_togo_logic.py" "${pkgdir}/usr/share/lufux/windows_togo_logic.py"
    install -Dm644 "${srcdir}/bcd_logic.py" "${pkgdir}/usr/share/lufux/bcd_logic.py"
    install -Dm644 "${srcdir}/speed_logic.py" "${pkgdir}/usr/share/lufux/speed_logic.py"
    install -Dm644 "${srcdir}/universal_logic.py" "${pkgdir}/usr/share/lufux/universal_logic.py"
    install -Dm644 "${srcdir}/deps_logic.py" "${pkgdir}/usr/share/lufux/deps_logic.py"
    install -Dm644 "${srcdir}/iso_logic.py" "${pkgdir}/usr/share/lufux/iso_logic.py"
    install -Dm644 "${srcdir}/udisks_logic.py" "${pkgdir}/usr/share/lufux/udisks_logic.py"

    install -Dm644 "${srcdir}/io.github.Advnirr.Lufux.desktop" "${pkgdir}/usr/share/applications/io.github.Advnirr.Lufux.desktop"
    install -Dm644 "${srcdir}/io.github.Advnirr.Lufux.metainfo.xml" "${pkgdir}/usr/share/metainfo/io.github.Advnirr.Lufux.metainfo.xml"
    install -Dm644 "${srcdir}/lufux.svg" "${pkgdir}/usr/share/icons/hicolor/scalable/apps/io.github.Advnirr.Lufux.svg"
}
