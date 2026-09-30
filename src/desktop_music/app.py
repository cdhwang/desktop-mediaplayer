"""Application bootstrap: builds the QApplication and shows the main window."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from desktop_music.constants import APP_NAME, ORG_NAME


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
    from desktop_music.ui.theme import DARK_QSS

    app.setStyleSheet(DARK_QSS)
    return app


def run(argv: list[str] | None = None) -> int:
    """Launch the GUI event loop. Returns the process exit code."""
    from desktop_music.ui.main_window import MainWindow

    app = create_app(argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
