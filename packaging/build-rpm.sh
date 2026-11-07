#!/bin/sh
# Builds dist/mousekit-VERSION-1.noarch.rpm from this checkout (needs rpmbuild).
set -eu

version=${1:?usage: packaging/build-rpm.sh VERSION}
root=$(cd "$(dirname "$0")/.." && pwd)
top=$(mktemp -d)
trap 'rm -rf "$top"' EXIT

rpmbuild -bb --quiet --define "_topdir $top" --define "pkg_version $version" --define "source_root $root" \
    "$root/packaging/mousekit.spec"
mkdir -p "$root/dist"
cp "$top"/RPMS/noarch/mousekit-"$version"-1.noarch.rpm "$root/dist/"
