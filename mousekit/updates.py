"""Update checks against the project's GitHub releases.

Every push to main publishes a release with the .deb and .rpm attached and the commit
message as its notes, so the changelog between two versions is the notes of
the releases in between.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from functools import cache
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__

REPO = "Athet-psl/mousekit-gamepro"
HOMEPAGE = f"https://github.com/{REPO}"
AUTHOR_URL = "https://github.com/Athet-psl"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
INSTALL_ROOT = Path("/usr/share/mousekit")  # where the .deb or .rpm puts the app
CHECK_INTERVAL = 3600
WINDOWS = sys.platform == "win32"
if WINDOWS:
    STATE_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "Mousekit"
    DOWNLOAD_DIR = STATE_DIR / "downloads"
else:
    STATE_DIR = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "mousekit"
    DOWNLOAD_DIR = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "mousekit"
NOTIFIED_PATH = STATE_DIR / "notified-version"


def parse_version(text):
    """(0, 2, 7) from "v0.2.7" or "0.2.7"; None if it isn't a version."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (text or "").strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def _published(releases):
    """(version, release) for real releases, newest first."""
    found = []
    for release in releases:
        version = parse_version(release.get("tag_name"))
        if version and not release.get("draft") and not release.get("prerelease"):
            found.append((version, release))
    return sorted(found, key=lambda item: item[0], reverse=True)


def newer_releases(releases, current=__version__):
    """Releases newer than `current`, newest first, from the GitHub API's list."""
    have = parse_version(current) or (0,)
    return [release for version, release in _published(releases) if version > have]


def recent_releases(releases, current=__version__, count=10):
    """The installed release and the ones before it, newest first."""
    have = parse_version(current) or (0,)
    return [release for version, release in _published(releases) if version <= have][:count]


def release_version(release):
    return release.get("tag_name", "").lstrip("v")


PACKAGES = {  # package format -> (asset name prefix, suffix)
    "deb": ("mousekit_", "_all.deb"),
    "rpm": ("mousekit-", ".noarch.rpm"),
    "setup": ("mousekit-setup-", ".exe"),
}


def find_asset(release, kind):
    """(file name, download URL, sha256 or None) of the release's package of this format, or None."""
    prefix, suffix = PACKAGES[kind]
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.startswith(prefix) and name.endswith(suffix):
            digest = asset.get("digest") or ""
            return name, asset["browser_download_url"], digest[7:] if digest.startswith("sha256:") else None
    return None


def setup_asset(release):
    """The release's Windows installer, or None."""
    return find_asset(release, "setup")


@cache
def package_format():
    """How this copy was installed: "setup" on Windows, "rpm" from the .rpm, otherwise "deb"."""
    if WINDOWS:
        return "setup"
    if shutil.which("rpm") and subprocess.run(["rpm", "-q", "--quiet", "mousekit"]).returncode == 0:
        return "rpm"
    return "deb"


def package_asset(release):
    """The release's package for this system: the installer on Windows, the .deb or .rpm elsewhere."""
    return find_asset(release, package_format())


def install_command(path, kind=None):
    """The command that installs the downloaded .deb or .rpm at `path`, run as root."""
    if (kind or package_format()) == "rpm":
        return ["/usr/bin/dnf", "install", "-y", str(path)]
    return ["/usr/bin/apt-get", "install", "-y", str(path)]


def changelog(releases):
    """Markdown changelog of the given releases, in the given order."""
    parts = []
    for release in releases:
        date = (release.get("published_at") or "")[:10]
        heading = f"### {release_version(release)}" + (f"  ·  {date}" if date else "")
        parts.append(heading + "\n\n" + (release.get("body") or "").strip())
    return "\n\n".join(parts)


def new_mouse_issue(name="", key="", dump=""):
    """Link to the "support for a new mouse" issue form, prefilled for this mouse."""
    fields = {"template": "new-mouse.yml"}
    if name or key:
        fields["title"] = f"Support: {name} ({key})"
        fields["model"] = name
        fields["usb-id"] = key
    if dump:
        fields["dump"] = dump
    return f"{HOMEPAGE}/issues/new?{urllib.parse.urlencode(fields)}"


def installed_from_package():
    """True when running from the .deb or .rpm (or the Windows installer), so updates can be installed;
    False in a source checkout."""
    if WINDOWS:
        return bool(getattr(sys, "frozen", False))
    return Path(__file__).resolve().is_relative_to(INSTALL_ROOT)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_releases(timeout=20):
    request = urllib.request.Request(RELEASES_API, headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"mousekit/{__version__}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def last_notified():
    try:
        return NOTIFIED_PATH.read_text().strip()
    except OSError:
        return ""


def set_notified(version):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    NOTIFIED_PATH.write_text(version + "\n")


def notify_update(version):
    """Desktop notification about a new version; its button opens Mousekit's About window."""
    if WINDOWS:
        from . import winnotify

        winnotify.notify(f"Mousekit {version} is available",
                         "Click to see what's new and install it.", winnotify.open_about)
        return
    if not shutil.which("notify-send"):
        return
    proc = subprocess.Popen(
        ["notify-send", "--app-name=Mousekit", "--icon=input-mouse", "--hint=string:desktop-entry:mousekit",
         "--action=open=What's new", f"Mousekit {version} is available",
         "See what's new and install it from Mousekit › About."],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    def wait():  # notify-send blocks until the notification is closed
        if proc.communicate()[0].strip() == "open":
            subprocess.Popen([shutil.which("mousekit") or "/usr/bin/mousekit", "--about"])

    threading.Thread(target=wait, daemon=True).start()
