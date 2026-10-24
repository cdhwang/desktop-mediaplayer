"""Module entry point so ``python -m desktop_music`` launches the app.

The Start-menu shortcut created by :func:`desktop_music.services.taskbar.
ensure_app_shortcut` targets ``pythonw.exe -m desktop_music``, so this module
must exist for that shortcut (and any manual ``-m`` launch) to work.
"""

from desktop_music import main

if __name__ == "__main__":
    raise SystemExit(main())
