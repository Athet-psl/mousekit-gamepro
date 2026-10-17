#!/bin/sh
# Builds dist/mousekit_VERSION_all.deb from this checkout.
set -eu

version=${1:?usage: packaging/build-deb.sh VERSION}
root=$(cd "$(dirname "$0")/.." && pwd)
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
pkg=$stage/mousekit
app=$pkg/usr/share/mousekit

mkdir -p "$app/bin" "$pkg/usr/bin" "$pkg/DEBIAN"
cp -r "$root/mousekit" "$app/"
find "$app" -name __pycache__ -prune -exec rm -rf {} +
rm -f "$app/mousekit/assets/gm500w-render.png"  # only the source of gm500w.png (tools/)
sed -i "s/^__version__ = .*/__version__ = \"$version\"/" "$app/mousekit/__init__.py"
install -m 755 "$root/bin/mousekit" "$root/bin/mousekitd" "$app/bin/"
ln -s ../share/mousekit/bin/mousekit "$pkg/usr/bin/mousekit"
ln -s ../share/mousekit/bin/mousekitd "$pkg/usr/bin/mousekitd"
install -D -m 644 "$root/data/mousekit.service" "$pkg/usr/lib/systemd/user/mousekit.service"
install -D -m 644 "$root/data/mousekit.desktop" "$pkg/usr/share/applications/mousekit.desktop"
install -D -m 644 "$root/data/70-mousekit.rules" "$pkg/usr/lib/udev/rules.d/70-mousekit.rules"
install -D -m 644 "$root/LICENSE" "$pkg/usr/share/doc/mousekit/copyright"
install -m 644 "$root/README.md" "$root/docs/GM500W-PROTOCOL.md" "$pkg/usr/share/doc/mousekit/"
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

find "$pkg" -type d -exec chmod 755 {} +
find "$pkg/usr" -type f -exec chmod 644 {} +
chmod 755 "$app/bin/mousekit" "$app/bin/mousekitd"

mkdir -p "$root/dist"
dpkg-deb --root-owner-group --build "$pkg" "$root/dist/mousekit_${version}_all.deb"
