pkgname=lufux-git
pkgver=1.4.1
pkgrel=1
pkgdesc="Create bootable USB drives on Linux, including Windows To Go"
arch=('any')
url="https://github.com/Advnirr/lufux"
license=('GPL3')
depends=('python-gobject' 'gtk4' 'libadwaita' 'wimlib' 'dosfstools' 'ntfs-3g' 'udisks2')
optdepends=('grub: boot MBR/NTFS Windows media on Legacy BIOS')
makedepends=('git' 'gettext')
source=("main.py" "i18n.py" "windows_logic.py" "windows_togo_logic.py" "bcd_logic.py" "speed_logic.py" "universal_logic.py" "deps_logic.py" "iso_logic.py" "udisks_logic.py" "io.github.Advnirr.Lufux.desktop" "io.github.Advnirr.Lufux.metainfo.xml" "lufux.svg")
sha256sums=('2f5cd0481c34225999944fbce5623adc5b4ba61e6d170439a29e6c4453d1db58'
            '0cdc971ff809763d10225aa3878250990241438de6ea85bcebedd7fad26ceee2'
            '52480ccfc84e74f50cc76a1e1530db4c8d41cdfef8bedbab6f137c8a15c7b4d8'
            'a8cbb5e912672cc92db3afc3c414f642a805dbda5b70db8ce44c6c9583a232a2'
            '3fcc097c0baa6c786b5903b64789e1027a74efa4da4f78c414dc414694945c16'
            'eb9c42cb5474e8cbbd0ceb49c3ca786b0328ee99c2892f40c30a28842c56623b'
            '559379fe35b35a9217688205ec6b6239dbdba53e665438770b686fa117e3e38b'
            '9631a831a55fb15678bf41df26a841a22c410cbf108c6ab8bf918276461a753b'
            '1aa2cd97a60cd49d761a9605cc7fa1d47ef0f6fca0cb1342ed9a2db395bb9bd4'
            '760f248ab79615af3d296003df121a26bdd91e55ef9a83a2db062d57333841b0'
            '34bf2767d1e54db44d2e76bd13459fb70f744ed03bd4a0224af12f12f5aa1281'
            'c96431dddcacbe85108ea5e86ab46ed06f46f2fe3c4cb546816fcb465207580c'
            '706e7d7c0ea396617b8cb9f15890cb616ceafab98237d7296c5b3c6aaba3fb2e')

package() {
    # the same files as the .deb and the .rpm, from this checkout
    sh "${startdir}/packaging/install.sh" "${pkgdir}"
}
