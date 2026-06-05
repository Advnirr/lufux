pkgname=lufux-git
pkgver=1.2.0
pkgrel=1
pkgdesc="Minimalist GUI tool to create bootable USB drives"
arch=('any')
url="https://github.com/Advnirr/lufux"
license=('GPL3')
depends=('python-gobject' 'gtk4' 'libadwaita' 'wimlib' 'rsync' 'parted' 'polkit' 'libarchive')
makedepends=('git')
source=("main.py" "windows_logic.py" "windows_togo_logic.py" "universal_logic.py" "deps_logic.py" "lufux.desktop" "lufux.svg")
sha256sums=('SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP')

package() {
    install -d "${pkgdir}/usr/share/lufux"

    install -Dm755 "${srcdir}/main.py" "${pkgdir}/usr/share/lufux/main.py"
    install -Dm644 "${srcdir}/windows_logic.py" "${pkgdir}/usr/share/lufux/windows_logic.py"
    install -Dm644 "${srcdir}/windows_togo_logic.py" "${pkgdir}/usr/share/lufux/windows_togo_logic.py"
    install -Dm644 "${srcdir}/universal_logic.py" "${pkgdir}/usr/share/lufux/universal_logic.py"
    install -Dm644 "${srcdir}/deps_logic.py" "${pkgdir}/usr/share/lufux/deps_logic.py"

    install -Dm644 "${srcdir}/lufux.desktop" "${pkgdir}/usr/share/applications/lufux.desktop"
    install -Dm644 "${srcdir}/lufux.svg" "${pkgdir}/usr/share/icons/hicolor/scalable/apps/lufux.svg"
}
