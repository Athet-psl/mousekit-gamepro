"""Entry point of mousekit.exe: the settings app, or `mousekit --dump` in a console."""

import sys

if sys.argv[1:2] == ["--dump"]:
    import ctypes

    # mousekit.exe is a windowed program: write to the console it was started from, if any.
    if ctypes.windll.kernel32.AttachConsole(-1):
        sys.stdout = open("CONOUT$", "w", encoding="utf-8")
        sys.stderr = sys.stdout
        sys.stdin = open("CONIN$", encoding="utf-8")
    from mousekit.dump import main

    main(sys.argv[2:])
else:
    from mousekit.ui import main

    main()
