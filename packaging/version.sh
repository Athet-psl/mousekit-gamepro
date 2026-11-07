#!/bin/sh
# Prints the version of this checkout: major.minor from mousekit/__init__.py, then the commit count.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
base=$(sed -n 's/^__version__ = "\([0-9]*\.[0-9]*\)\..*/\1/p' "$root/mousekit/__init__.py")
echo "$base.$(git -C "$root" rev-list --count HEAD)"
