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
sha256sums=('152354222d88058650f9740e41dbcd7145438d1770da568611551a725dcd9003'
            '7be71fc05e34f5524500f5cd9ca41425c38c14c070f7d68450b93a9fbf26c69c'
            '75c59c56c168cf24f6b403f140ef447e8a88a579a3896da64f85a9d70c62a7b3'
            '3fcc097c0baa6c786b5903b64789e1027a74efa4da4f78c414dc414694945c16'
            'eb9c42cb5474e8cbbd0ceb49c3ca786b0328ee99c2892f40c30a28842c56623b'
            '5ede5b95a37da597fd20bca7166c4c0b2dc50542cb857d29b0c2968cea6d6d33'
            '9631a831a55fb15678bf41df26a841a22c410cbf108c6ab8bf918276461a753b'
            '1aa2cd97a60cd49d761a9605cc7fa1d47ef0f6fca0cb1342ed9a2db395bb9bd4'
            '760f248ab79615af3d296003df121a26bdd91e55ef9a83a2db062d57333841b0'
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
