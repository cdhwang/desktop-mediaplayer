"""Desktop Music - a PotPlayer-style media player built with PyQt6 and libVLC."""

__version__ = "0.1.0"


def _setup_logging() -> None:
    """Configure logging from the DESKTOP_MUSIC_LOG env var.

    Default level is WARNING (quiet). Set ``DESKTOP_MUSIC_LOG=INFO`` to see
    remote claim/release events, or ``=DEBUG`` for per-poll state snapshots
    (useful when debugging the web remote's mute / position sync).
    """
    import logging
    import os

    level_name = os.environ.get("DESKTOP_MUSIC_LOG", "WARNING").upper()
    level = getattr(logging, level_name, logging.WARNING)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> int:
    """Console entry point defined in pyproject.toml [project.scripts]."""
    _setup_logging()
    from desktop_music.app import run

    return run()
