"""Starting the service on Windows: what systemd --user does on Linux.

The service runs as a background process of the logged-in user (it needs
their desktop for the input hooks), started at sign-in from the registry's
Run key, and stopped by asking it over its socket.
"""

import json
import os
import socket
import subprocess
import sys
import time
import winreg
from pathlib import Path

from . import config

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Mousekit"
ROOT = Path(__file__).resolve().parent.parent


def _frozen():
    return bool(getattr(sys, "frozen", False))


def command(program, *args):
    """[executable, args...] for "mousekit" (the app) or "mousekitd" (the service), installed or from source."""
    if _frozen():
        return [str(Path(sys.executable).with_name(f"{program}.exe")), *args]
    python = Path(sys.executable)
    windowless = python.with_name("pythonw.exe")
    return [str(windowless if windowless.exists() else python), str(ROOT / "bin" / program), *args]


def _quoted(argv):
    return subprocess.list2cmdline(argv)


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
            return True
    except OSError:
        return False


def set_autostart(on):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if on:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, _quoted(command("mousekitd")))
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass


def is_running():
    from .windaemon import running

    return running()


def start():
    """Start the service in the background and have it start at every sign-in."""
    set_autostart(True)
    if is_running():
        return
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    subprocess.Popen(command("mousekitd"), creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop(timeout=3.0):
    """Ask a running service to quit; True once it's gone."""
    try:
        info = json.loads(config.SOCKET_PATH.read_text(encoding="utf-8"))
        with socket.create_connection(("127.0.0.1", info["port"]), timeout=1) as conn:
            conn.sendall(f"{info['token']}\nquit\n".encode())
    except (OSError, ValueError, KeyError):
        pass
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_running():
            return True
        time.sleep(0.1)
    return not is_running()


def restart():
    stop()
    start()


def launch_app(*args):
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(command("mousekit", *args), creationflags=flags, close_fds=True)


def connection_info():
    """(port, token) of the running service, or None."""
    try:
        info = json.loads(config.SOCKET_PATH.read_text(encoding="utf-8"))
        return int(info["port"]), str(info["token"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


assert os.name == "nt", "winservice is for Windows"
