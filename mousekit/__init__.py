"""Mousekit: mouse settings for KDE Plasma and Windows."""

__version__ = "0.2.0"  # the release build sets the real one
__author__ = "Athet-psl"

try:  # the Windows build writes the release version here
    from ._build import __version__  # noqa: F401
except ImportError:
    pass
