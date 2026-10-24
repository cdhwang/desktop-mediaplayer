"""Loader for the remote-control HTML page.

The page lives in ``remote.html`` (same directory as this module) so it can
be edited directly without touching Python source.  At runtime the file is
read on each request, which means changes take effect on the next browser
reload without restarting the app.

``REMOTE_PAGE_HTML`` is kept as a module-level cached string for callers that
imported it as a constant (e.g. existing tests).  Use :func:`load_remote_page`
when you want the freshest copy from disk.
"""

from __future__ import annotations

import pathlib

_HTML_PATH = pathlib.Path(__file__).with_name("remote.html")

# Eager load so import errors surface immediately and tests that reference
# the constant still work.  A missing file raises FileNotFoundError here.
REMOTE_PAGE_HTML: str = _HTML_PATH.read_text(encoding="utf-8")


def load_remote_page() -> str:
    """Return the HTML page content, reading from disk each time.

    This allows live editing of ``remote.html`` during development: refresh
    the browser and the latest version is served without restarting the app.
    Falls back to the module-level cached string if the file has disappeared.
    """
    try:
        return _HTML_PATH.read_text(encoding="utf-8")
    except OSError:
        return REMOTE_PAGE_HTML
