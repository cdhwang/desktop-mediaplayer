"""The single-file HTML remote-control page.

Served verbatim by :class:`~desktop_music.services.remote.remote_service.RemoteService`
at ``/`` and ``/remote``. It is intentionally dependency-free (no CDN, no
build step): one HTML string with inline CSS and vanilla JS that polls the
REST API and renders the controls. Kept here as a Python string so it ships
inside the package with no extra data-file packaging.

The page talks to the same origin it was loaded from, so no host/port needs
to be configured in the browser.
"""

from __future__ import annotations

REMOTE_PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>Desktop Music Remote</title>
<style>
  :root {
    --bg: #15171c;
    --panel: #1e2128;
    --panel2: #272b34;
    --fg: #e8eaed;
    --muted: #9aa0aa;
    --accent: #4c8dff;
    --accent2: #2f6fd6;
    --playing: #223a66;
    --border: #333843;
  }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  html, body {
    margin: 0; padding: 0; background: var(--bg); color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    height: 100%;
  }
  body { display: flex; flex-direction: column; max-width: 680px; margin: 0 auto; }
  header {
    padding: 14px 16px; background: var(--panel); border-bottom: 1px solid var(--border);
    position: sticky; top: 0; z-index: 5;
  }
  .conn { font-size: 12px; color: var(--muted); }
  .conn.ok { color: #58d68d; }
  .conn.bad { color: #e67e7e; }
  .now-title { font-size: 18px; font-weight: 600; margin-top: 4px; word-break: break-word; }
  .now-sub { font-size: 13px; color: var(--muted); margin-top: 2px; }
  .seek-row { display: flex; align-items: center; gap: 8px; margin-top: 10px; }
  .time { font-size: 12px; color: var(--muted); width: 44px; text-align: center; font-variant-numeric: tabular-nums; }
  input[type=range] { width: 100%; accent-color: var(--accent); }
  .controls { padding: 12px 16px; background: var(--panel); border-bottom: 1px solid var(--border); }
  .row { display: flex; gap: 10px; justify-content: center; align-items: center; margin: 8px 0; }
  button {
    background: var(--panel2); color: var(--fg); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px 14px; font-size: 16px; cursor: pointer;
    min-width: 52px; min-height: 48px; transition: background .12s, border-color .12s;
  }
  button:active { background: var(--accent2); }
  button.wide { flex: 1; }
  button.primary { background: var(--accent); border-color: var(--accent); font-weight: 600; }
  button.toggled { border-color: var(--accent); color: var(--accent); }
  .vol-row { display: flex; align-items: center; gap: 10px; }
  .vol-row input[type=range] { flex: 1; }
  .vol-val { width: 42px; text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }
  .list { flex: 1; overflow-y: auto; padding: 6px 10px 20px; }
  .track {
    display: flex; align-items: center; gap: 10px; padding: 12px 12px;
    border-radius: 10px; border: 1px solid transparent; cursor: pointer;
  }
  .track:active { background: var(--panel2); }
  .track.playing { background: var(--playing); border-color: var(--accent2); }
  .track .idx { color: var(--muted); width: 26px; text-align: right; font-variant-numeric: tabular-nums; font-size: 13px; }
  .track .meta { flex: 1; min-width: 0; }
  .track .t { font-size: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .track .a { font-size: 12px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .track .dur { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
  .eq { color: var(--accent); font-size: 14px; }
  .section-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; padding: 8px 12px 2px; }
</style>
</head>
<body>
  <header>
    <div class="conn" id="conn">connecting…</div>
    <div class="now-title" id="nowTitle">—</div>
    <div class="now-sub" id="nowSub"></div>
    <div class="seek-row">
      <span class="time" id="curTime">0:00</span>
      <input type="range" id="seek" min="0" max="1000" value="0">
      <span class="time" id="durTime">0:00</span>
    </div>
  </header>

  <div class="controls">
    <div class="row">
      <button id="btnPrev" title="Previous">⏮</button>
      <button id="btnPlay" class="primary wide" title="Play/Pause">⏯</button>
      <button id="btnNext" title="Next">⏭</button>
      <button id="btnStop" title="Stop">⏹</button>
    </div>
    <div class="row vol-row">
      <button id="btnVolDown" title="Volume down">🔉</button>
      <input type="range" id="vol" min="0" max="100" value="100">
      <button id="btnVolUp" title="Volume up">🔊</button>
      <span class="vol-val" id="volVal">100</span>
    </div>
    <div class="row">
      <button id="btnMute" class="wide" title="Mute">🔇 Mute</button>
      <button id="btnShuffle" class="wide" title="Shuffle">🔀 Shuffle</button>
      <button id="btnRepeat" class="wide" title="Repeat">🔁 Repeat</button>
    </div>
  </div>

  <div class="section-label">Playlist</div>
  <div class="list" id="list"></div>

<script>
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var seeking = false;
  var volDragging = false;
  var lastPlaylistSig = "";

  function fmt(ms) {
    ms = Math.max(0, ms | 0);
    var s = Math.floor(ms / 1000);
    var m = Math.floor(s / 60);
    s = s % 60;
    return m + ":" + (s < 10 ? "0" : "") + s;
  }

  function api(path, opts) {
    return fetch(path, opts).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  function post(path, body) {
    return api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined
    }).then(applyState).catch(function () {});
  }

  function command(id) { return post("/api/command/" + id); }

  function setConn(ok) {
    var el = $("conn");
    if (ok) { el.textContent = "connected"; el.className = "conn ok"; }
    else { el.textContent = "disconnected — retrying…"; el.className = "conn bad"; }
  }

  function applyState(s) {
    if (!s) return;
    setConn(true);
    var cur = s.current;
    $("nowTitle").textContent = cur ? cur.title : "Nothing playing";
    var sub = [];
    if (s.state) sub.push(s.state);
    if (cur && cur.artist) sub.unshift(cur.artist);
    $("nowSub").textContent = sub.join("  ·  ");

    // Seek bar (skip while the user is dragging).
    if (!seeking) {
      var len = s.length_ms || 0;
      var pos = s.position_ms || 0;
      $("seek").value = len > 0 ? Math.round((pos / len) * 1000) : 0;
      $("curTime").textContent = fmt(pos);
      $("durTime").textContent = fmt(len);
    }

    // Volume (skip while dragging).
    if (!volDragging) {
      $("vol").value = s.volume;
      $("volVal").textContent = s.volume;
    }

    // Toggles.
    $("btnMute").classList.toggle("toggled", !!s.muted);
    $("btnShuffle").classList.toggle("toggled", !!s.shuffle);
    var rep = s.repeat || "none";
    var repBtn = $("btnRepeat");
    repBtn.classList.toggle("toggled", rep !== "none");
    repBtn.textContent = rep === "one" ? "🔂 Repeat 1"
                        : rep === "all" ? "🔁 Repeat All"
                        : "🔁 Repeat";
    $("btnPlay").textContent = s.state === "playing" ? "⏸" : "▶";
    highlightPlaying(s.current_index);
  }

  function highlightPlaying(idx) {
    var rows = document.querySelectorAll(".track");
    rows.forEach(function (row) {
      var r = parseInt(row.getAttribute("data-index"), 10);
      row.classList.toggle("playing", r === idx);
    });
  }

  function renderPlaylist(pl) {
    if (!pl) return;
    // Cheap change detection so we don't rebuild the DOM every poll.
    var sig = pl.count + ":" + pl.tracks.map(function (t) { return t.title; }).join("|");
    if (sig === lastPlaylistSig) {
      highlightPlaying(pl.current_index);
      return;
    }
    lastPlaylistSig = sig;
    var list = $("list");
    list.innerHTML = "";
    pl.tracks.forEach(function (t) {
      var row = document.createElement("div");
      row.className = "track" + (t.playing ? " playing" : "");
      row.setAttribute("data-index", t.index);
      var idx = document.createElement("div");
      idx.className = "idx";
      idx.textContent = (t.index + 1);
      var meta = document.createElement("div");
      meta.className = "meta";
      var title = document.createElement("div");
      title.className = "t";
      title.textContent = t.title;
      meta.appendChild(title);
      if (t.artist) {
        var artist = document.createElement("div");
        artist.className = "a";
        artist.textContent = t.artist;
        meta.appendChild(artist);
      }
      var dur = document.createElement("div");
      dur.className = "dur";
      dur.textContent = t.duration_ms ? fmt(t.duration_ms) : "";
      row.appendChild(idx);
      row.appendChild(meta);
      row.appendChild(dur);
      row.addEventListener("click", function () {
        post("/api/play", { index: t.index });
      });
      list.appendChild(row);
    });
  }

  // -- wiring --
  $("btnPlay").addEventListener("click", function () { command("play_pause"); });
  $("btnPrev").addEventListener("click", function () { command("previous"); });
  $("btnNext").addEventListener("click", function () { command("next"); });
  $("btnStop").addEventListener("click", function () { command("stop"); });
  $("btnVolUp").addEventListener("click", function () { command("volume_up"); });
  $("btnVolDown").addEventListener("click", function () { command("volume_down"); });
  $("btnMute").addEventListener("click", function () { command("mute"); });
  $("btnShuffle").addEventListener("click", function () { command("toggle_shuffle"); });
  $("btnRepeat").addEventListener("click", function () { command("cycle_repeat"); });

  var seek = $("seek");
  seek.addEventListener("input", function () {
    seeking = true;
  });
  seek.addEventListener("change", function () {
    var frac = seek.value / 1000;
    post("/api/seek", { fraction: frac }).then(function () { seeking = false; });
    setTimeout(function () { seeking = false; }, 400);
  });

  var vol = $("vol");
  vol.addEventListener("input", function () {
    volDragging = true;
    $("volVal").textContent = vol.value;
  });
  vol.addEventListener("change", function () {
    post("/api/volume", { value: parseInt(vol.value, 10) });
    setTimeout(function () { volDragging = false; }, 400);
  });

  // -- polling loop --
  function pollState() {
    api("/api/state").then(applyState).catch(function () { setConn(false); });
  }
  function pollPlaylist() {
    api("/api/playlist").then(renderPlaylist).catch(function () {});
  }

  pollState();
  pollPlaylist();
  setInterval(pollState, 1000);
  setInterval(pollPlaylist, 3000);
})();
</script>
</body>
</html>
"""
