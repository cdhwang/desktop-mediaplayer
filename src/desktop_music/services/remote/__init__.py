"""Remote-control service: lets a browser on the same LAN drive the player
over plain HTTP.

The desktop runs a lightweight HTTP server that serves a single self-contained
HTML remote page plus a small JSON REST API. The page polls the API to stay in
sync -- there is no WebSocket channel and no network discovery; the user opens
``http://<desktop-ip>:8787/`` in a phone/tablet/desktop browser.

Modules:

* :mod:`state`          -- pure serialization of controller/playlist -> dicts
* :mod:`http_server`    -- minimal HTTP/1.1 server on top of ``QTcpServer``
* :mod:`web`            -- the single-file HTML remote page
* :mod:`remote_service` -- wires the HTTP routes to the controller/model
"""

from __future__ import annotations
