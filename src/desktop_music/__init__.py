"""Desktop Music - a PotPlayer-style media player built with PyQt6 and libVLC."""

__version__ = "0.1.0"


def main() -> int:
    """Console entry point defined in pyproject.toml [project.scripts]."""
    from desktop_music.app import run

    return run()
