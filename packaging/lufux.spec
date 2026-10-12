Name:           lufux
Version:        1.3.9
Release:        1%{?dist}
Summary:        Create bootable USB drives, including Windows To Go
License:        GPL-3.0-or-later
URL:            https://github.com/Advnirr/lufux
Source0:        %{url}/archive/refs/tags/v%{version}-stable.tar.gz
BuildArch:      noarch

Requires:       python3
Requires:       python3-gobject
Requires:       gtk4 >= 4.10
Requires:       libadwaita >= 1.5
Requires:       wimlib-utils
Requires:       dosfstools
Requires:       ntfsprogs
Requires:       udisks2
Suggests:       grub2-tools
Suggests:       grub2-pc-modules

%description
A GTK4/libadwaita tool that writes ISOHybrid images with dd, builds Windows
installation media (GPT/FAT32 for UEFI, MBR/NTFS for Legacy BIOS) and installs
Windows To Go onto a USB drive.

%prep
%autosetup -n lufux-%{version}-stable

%build

%install
sh packaging/install.sh %{buildroot}

%files
%license LICENSE
%doc README.md
%{_datadir}/lufux/
%{_datadir}/applications/io.github.Advnirr.Lufux.desktop
%{_datadir}/metainfo/io.github.Advnirr.Lufux.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/io.github.Advnirr.Lufux.svg
