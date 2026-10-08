"""Application bootstrap: builds the QApplication and shows the main window."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from desktop_music.constants import APP_NAME, ORG_NAME, load_app_icon


def create_app(argv: list[str] | None = None) -> QApplication:
    """Create (or reuse) the QApplication instance.

    Reusing an existing instance keeps pytest-qt happy, since only one
    QApplication may exist per process.
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    icon = load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    from desktop_music.ui.theme import DARK_QSS

    app.setStyleSheet(DARK_QSS)
    return app


def run(argv: list[str] | None = None) -> int:
    """Launch the GUI event loop. Returns the process exit code.

    Any positional command-line arguments are treated as media files to
    open. When files are given, the playlist is populated with every
    playable file in the directory of the *first* argument, and playback
    starts on that first argument.
    """
    from desktop_music.ui.main_window import MainWindow

    app = create_app(argv)

    raw_args = argv if argv is not None else sys.argv
    # QApplication strips recognised Qt options; use its remaining args.
    remaining = app.arguments()[1:] if len(app.arguments()) > 1 else raw_args[1:]
    initial_media = [a for a in remaining if not a.startswith("-")]

    window = MainWindow(initial_media=initial_media or None)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
