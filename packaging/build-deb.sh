#!/bin/sh
# Builds dist/mousekit_VERSION_all.deb from this checkout.
set -eu

version=${1:?usage: packaging/build-deb.sh VERSION}
root=$(cd "$(dirname "$0")/.." && pwd)
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
pkg=$stage/mousekit

"$root/packaging/stage.sh" "$pkg" "$version"
mkdir -p "$pkg/DEBIAN"
install -m 755 "$root/packaging/postinst" "$root/packaging/prerm" "$root/packaging/postrm" "$pkg/DEBIAN/"

cat > "$pkg/DEBIAN/control" <<CONTROL
Package: mousekit
Version: $version
Architecture: all
Maintainer: Athet-psl <186676948+Athet-psl@users.noreply.github.com>
Installed-Size: $(du -sk "$pkg/usr" | cut -f1)
Depends: python3, python3-evdev, python3-pyqt6, python3-dbus
Recommends: pkexec | policykit-1, libnotify-bin
Section: utils
Priority: optional
Homepage: https://github.com/Athet-psl/mousekit-gamepro
Description: mouse settings for KDE Plasma: GamePro lighting, DPI, buttons, gestures
 Mousekit for GamePro sets the lighting, DPI stages and hardware buttons of
 GamePro mice (GM500W) and saves them to the mouse. For any mouse it adds
 button remapping and hold-and-swipe gestures on KDE Plasma.
CONTROL

chmod 755 "$pkg/DEBIAN"
mkdir -p "$root/dist"
dpkg-deb --root-owner-group --build "$pkg" "$root/dist/mousekit_${version}_all.deb"
