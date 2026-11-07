#!/bin/sh
# Installs Mousekit into ROOT (a package's staging tree) as version VERSION. Used by build-deb.sh and mousekit.spec.
set -eu

pkg=${1:?usage: packaging/stage.sh ROOT VERSION}
version=${2:?usage: packaging/stage.sh ROOT VERSION}
root=$(cd "$(dirname "$0")/.." && pwd)
app=$pkg/usr/share/mousekit

mkdir -p "$app/bin" "$pkg/usr/bin"
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

find "$pkg/usr" -type d -exec chmod 755 {} +
find "$pkg/usr" -type f -exec chmod 644 {} +
chmod 755 "$app/bin/mousekit" "$app/bin/mousekitd"
