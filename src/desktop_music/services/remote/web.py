"""The single-file HTML remote-control page.

Served verbatim by :class:`~desktop_music.services.remote.remote_service.RemoteService`
at ``/`` and ``/remote``. It is intentionally dependency-free (no CDN, no
build step): one HTML string with inline CSS and vanilla JS that polls the
REST API and renders the controls. Kept here as a Python string so it ships
inside the package with no extra data-file packaging.

The page talks to the same origin it was loaded from, so no host/port needs
to be configured in the browser.

Audio playback model ("control separation")
--------------------------------------------
The desktop player is muted and only *loads* tracks in remote mode; the
browser is the sole audio source. A hidden ``<audio>`` element plays MP3
transcoded on demand from ``/api/audio/{index}``.

The desktop's ``current_index`` (from ``/api/state``) is the single "what
should be playing" signal. Track clicks, next/previous and auto-advance all
work by changing that index on the desktop (which owns shuffle/repeat); the
browser simply watches the polled index and (re)loads the matching audio
whenever it changes. The browser owns transport (play/pause/seek/volume) on
the ``<audio>`` element and periodically reports its position/state back via
``POST /api/remote/state`` so the desktop UI can mirror progress.
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
  .conn.loading { color: var(--accent); }
  .now-title { font-size: 18px; font-weight: 600; margin-top: 4px; word-break: break-word; }
  .now-sub { font-size: 13px; color: var(--muted); margin-top: 2px; }
  .now-cover-wrap { display: flex; justify-content: center; margin-top: 12px; }
  .now-cover {
    width: 180px; height: 180px; border-radius: 12px; object-fit: cover;
    background: var(--panel2); border: 1px solid var(--border);
    display: none;
  }
  .now-cover.show { display: block; }
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
  /* Muted is a distinct, filled "warning" state so it's obvious at a glance
     and not confused with the accent-outline of shuffle/repeat toggles. */
  button#btnMute.muted {
    background: #5a2730; border-color: #e67e7e; color: #ffd9d9; font-weight: 600;
  }
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
  .track .thumb {
    width: 40px; height: 40px; border-radius: 6px; object-fit: cover;
    background: var(--panel2); flex: 0 0 auto;
  }
  .track .meta { flex: 1; min-width: 0; }
  .track .t { font-size: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .track .a { font-size: 12px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .track .dur { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
  .track .del {
    flex: 0 0 auto; min-width: 32px; min-height: 32px; padding: 4px 8px;
    font-size: 15px; line-height: 1; border-radius: 8px; color: var(--muted);
    background: transparent; border: 1px solid transparent;
  }
  .track .del:hover, .track .del:active { color: #e67e7e; border-color: var(--border); background: var(--panel2); }
  .eq { color: var(--accent); font-size: 14px; }
  .listen-note { font-size: 12px; color: var(--muted); text-align: center; min-height: 16px; padding: 2px 8px; }
  .listen-note.bad { color: #e67e7e; }
  .section-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; padding: 8px 12px 2px; }
</style>
</head>
<body>
  <!-- The real audio player. Hidden; the browser is the sole audio source
       while the desktop stays muted in remote mode. -->
  <audio id="audioEl" preload="auto" style="display:none"></audio>

  <header>
    <div class="conn" id="conn">connecting…</div>
    <div class="now-title" id="nowTitle">—</div>
    <div class="now-sub" id="nowSub"></div>
    <div class="now-cover-wrap">
      <img class="now-cover" id="nowCover" alt="">
    </div>
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
      <button id="btnMute" class="wide" title="Mute">🔊 Sound on</button>
      <button id="btnShuffle" class="wide" title="Shuffle">🔀 Shuffle</button>
      <button id="btnRepeat" class="wide" title="Repeat">🔁 Repeat</button>
    </div>
    <div class="row">
      <button id="btnListen" class="wide" title="Play the audio in this browser">🎧 Listen here</button>
    </div>
    <div class="listen-note" id="listenNote"></div>
  </div>

  <div class="section-label">Playlist</div>
  <div class="list" id="list"></div>

<script>
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var audio = $("audioEl");

  var seeking = false;       // user dragging the seek bar
  var volDragging = false;   // user dragging the volume slider
  var lastPlaylistSig = "";
  var loadedIndex = -1;      // index currently loaded into <audio>
  var loadedSig = "";        // identity of the loaded track (title|artist|dur|cue)
  var userVolume = 1.0;      // 0..1, applied to the <audio> element
  var muted = false;
  var loading = false;       // transcode/buffering in progress
  var pendingSeekMs = 0;     // one-shot seek to apply once metadata is ready

  // Audio-claim state. The desktop keeps its own audio until this browser
  // explicitly claims it via the "Listen here" toggle. Only when `claimed`
  // is true does this browser load/play audio and report heartbeats. The
  // token identifies this browser's claim to the desktop (single holder).
  var claimed = false;
  var audioToken = null;
  var claimPending = false;  // a claim/release request is in flight

  function genToken() {
    try {
      if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    } catch (e) {}
    return "c" + Date.now().toString(36) + Math.random().toString(36).slice(2);
  }

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

  // Fire-and-forget POST that does NOT re-apply the returned state (used for
  // the frequent remote-state report so it can't fight the audio element).
  function postQuiet(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined
    }).catch(function () {});
  }

  function command(id) { return post("/api/command/" + id); }

  function setConn(kind) {
    var el = $("conn");
    if (kind === "loading") { el.textContent = "loading track…"; el.className = "conn loading"; }
    else if (kind === "ok") { el.textContent = "connected"; el.className = "conn ok"; }
    else { el.textContent = "disconnected — retrying…"; el.className = "conn bad"; }
  }

  // -- audio claim: take/relinquish the desktop audio ---------------------

  function setListenNote(msg, bad) {
    var el = $("listenNote");
    el.textContent = msg || "";
    el.className = "listen-note" + (bad ? " bad" : "");
  }

  // Reflect the current mute state on the button with a clear icon + label
  // and a distinct "muted" style, so it's unambiguous whether sound is off.
  function updateMuteButton() {
    var btn = $("btnMute");
    btn.classList.toggle("muted", muted);
    btn.textContent = muted ? "🔇 Muted" : "🔊 Sound on";
    btn.setAttribute("aria-pressed", muted ? "true" : "false");
    btn.setAttribute("title", muted ? "Unmute" : "Mute");
  }

  function updateListenButton() {
    var btn = $("btnListen");
    btn.classList.toggle("toggled", claimed);
    btn.textContent = claimed ? "🎧 Listening here" : "🎧 Listen here";
  }

  function claimAudio() {
    if (claimPending || claimed) return;
    claimPending = true;
    if (!audioToken) audioToken = genToken();
    fetch("/api/audio/claim", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: audioToken })
    }).then(function (r) {
      // NOTE: do not clear claimPending here. Keeping it set until we have
      // either taken the claim (claimed=true) or definitively failed closes
      // the window where a concurrent poll could latch the desktop's mute
      // onto <audio> between "request done" and "claim applied".
      if (r.status === 409) {
        claimPending = false;
        setListenNote("Another device is already listening.", true);
        return null;
      }
      if (!r.ok) {
        claimPending = false;
        setListenNote("Could not start listening.", true);
        return null;
      }
      return r.json();
    }).then(function (s) {
      if (!s) return;
      claimed = true;
      claimPending = false;
      // The browser is now the audio source. Start from an unmuted <audio>
      // so the mute button reflects the browser, not the (always-muted)
      // desktop backend.
      audio.muted = false;
      muted = false;
      setListenNote("");
      updateListenButton();
      updateMuteButton();
      applyState(s);
      // Load whatever the desktop considers current and resume from where it
      // was (claim hands over the position, not a restart at 0).
      if (typeof s.current_index === "number" && s.current_index >= 0) {
        var resumeMs = (typeof s.resume_ms === "number") ? s.resume_ms : 0;
        var autoplay = (s.resume_playing !== false);  // default to playing
        try { console.log("[remote] claim resume: index=" + s.current_index + " resume_ms=" + resumeMs + " playing=" + autoplay); } catch (e) {}
        loadIndex(s.current_index, autoplay, trackSig(s.current), resumeMs);
      }
    }).catch(function () {
      claimPending = false;
      setListenNote("Could not start listening.", true);
    });
  }

  function releaseAudio(useBeacon) {
    try { console.log("[remote] releaseAudio: token=" + audioToken + " useBeacon=" + !!useBeacon); } catch (e) {}
    if (!audioToken) { claimed = false; updateListenButton(); return; }
    var body = JSON.stringify({ token: audioToken });
    // On page unload, a beacon survives the teardown; otherwise use fetch.
    if (useBeacon && navigator.sendBeacon) {
      try { navigator.sendBeacon("/api/audio/release", new Blob([body], { type: "application/json" })); } catch (e) {}
    } else {
      fetch("/api/audio/release", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body
      }).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (s) {
          try {
            console.log("[remote] release response: " +
              (s ? ("remote_mode=" + s.remote_mode + " muted=" + s.muted +
                    " pos=" + s.position_ms + " state=" + s.state) : "null"));
          } catch (e) {}
          // Reflect the desktop's restored state immediately.
          if (s) applyState(s);
        }).catch(function () {});
    }
    claimed = false;
    audio.pause();
    setListenNote("");
    updateListenButton();
  }

  function toggleListen() {
    if (claimed) releaseAudio(false);
    else claimAudio();
  }

  // -- audio element: load / transport ------------------------------------

  // A stable identity for a track, independent of its playlist index. Used
  // so a deletion that merely shifts indices does not restart the currently
  // playing track -- we only reload when the identity actually changes.
  function trackSig(t) {
    if (!t) return "";
    return [t.title || "", t.artist || "", t.duration_ms || 0,
            t.is_cue_track ? 1 : 0].join("|");
  }

  function loadIndex(index, autoplay, sig, seekMs) {
    if (index < 0) return;
    // Only this browser loads/plays audio while it holds the claim. Without
    // a claim the desktop is the audio source, so stay silent.
    if (!claimed) return;
    loadedIndex = index;
    loadedSig = sig || "";
    loading = true;
    setConn("loading");
    // Apply a one-shot seek once the track's metadata (duration) is ready,
    // so taking over the audio resumes where the desktop was instead of 0.
    pendingSeekMs = (seekMs && seekMs > 0) ? seekMs : 0;
    audio.src = "/api/audio/" + index;
    audio.load();
    if (autoplay) {
      var p = audio.play();
      if (p && p.catch) { p.catch(function () {}); }
    }
  }

  function togglePlay() {
    // When this browser is not the audio source, the play/pause button
    // controls the *desktop's* playback instead of the local <audio>.
    if (!claimed) {
      command("play_pause");
      return;
    }
    if (loadedIndex < 0) {
      // Nothing loaded yet: load whatever the desktop considers current.
      api("/api/state").then(function (s) {
        if (s && s.current_index >= 0) {
          loadIndex(s.current_index, true, trackSig(s.current));
        }
      }).catch(function () {});
      return;
    }
    if (audio.paused) {
      var p = audio.play();
      if (p && p.catch) { p.catch(function () {}); }
    } else {
      audio.pause();
    }
  }

  // Report the browser's own playback position/state to the desktop so its
  // UI mirrors what the listener actually hears.
  function reportState() {
    // Only the audio holder reports position/state; this doubles as the
    // claim heartbeat, so it must carry the token.
    if (!claimed || !audioToken) return;
    var state = loading ? "buffering"
              : audio.ended ? "ended"
              : audio.paused ? "paused"
              : "playing";
    postQuiet("/api/remote/state", {
      token: audioToken,
      position_ms: Math.round((audio.currentTime || 0) * 1000),
      length_ms: Math.round((isFinite(audio.duration) ? audio.duration : 0) * 1000),
      state: state
    });
  }

  audio.addEventListener("loadedmetadata", function () {
    loading = false;
    setConn("ok");
    // Resume at the position handed over from the desktop (claim), once we
    // know the duration so we can clamp. One-shot.
    if (pendingSeekMs > 0) {
      var dur = isFinite(audio.duration) ? audio.duration : 0;
      var target = pendingSeekMs / 1000;
      if (dur > 0) target = Math.min(target, Math.max(0, dur - 0.25));
      try { audio.currentTime = target; } catch (e) {}
      try { console.log("[remote] resume seek to " + target.toFixed(2) + "s (req " + pendingSeekMs + "ms, dur " + dur + "s)"); } catch (e) {}
      pendingSeekMs = 0;
    }
    updateProgress();
  });
  audio.addEventListener("canplay", function () { loading = false; setConn("ok"); });
  audio.addEventListener("waiting", function () { loading = true; setConn("loading"); });
  audio.addEventListener("playing", function () { loading = false; setConn("ok"); });
  audio.addEventListener("timeupdate", function () { if (!seeking) updateProgress(); });
  audio.addEventListener("play", function () { $("btnPlay").textContent = "⏸"; reportState(); });
  audio.addEventListener("pause", function () { $("btnPlay").textContent = "▶"; reportState(); });
  audio.addEventListener("ended", function () {
    reportState();
    // Let the desktop decide the next track (it owns shuffle/repeat); the
    // polling loop will then pick up the new current_index and load it.
    command("next");
  });
  audio.addEventListener("error", function () { loading = false; setConn("bad"); });

  function updateProgress() {
    var dur = isFinite(audio.duration) ? audio.duration : 0;
    var pos = audio.currentTime || 0;
    $("seek").value = dur > 0 ? Math.round((pos / dur) * 1000) : 0;
    $("curTime").textContent = fmt(pos * 1000);
    $("durTime").textContent = fmt(dur * 1000);
  }

  // -- state / playlist rendering -----------------------------------------

  function applyState(s) {
    if (!s) return;
    if (!loading) setConn("ok");
    var cur = s.current;
    $("nowTitle").textContent = cur ? cur.title : "Nothing playing";
    var sub = [];
    if (cur && cur.artist) sub.push(cur.artist);
    $("nowSub").textContent = sub.join("  ·  ");

    // Follow the desktop's current track. Compare the track *identity*, not
    // its index: a deletion elsewhere in the list can shift the current
    // track's index without changing what is playing. Only (re)load the
    // audio when the identity actually changes; a pure index shift just
    // updates our bookkeeping so playback continues uninterrupted.
    if (typeof s.current_index === "number" && s.current_index >= 0) {
      var sig = trackSig(s.current);
      if (loadedIndex < 0 || sig !== loadedSig) {
        loadIndex(s.current_index, true, sig);
      } else if (s.current_index !== loadedIndex) {
        // Same track, new index (list was reordered/trimmed): keep playing.
        loadedIndex = s.current_index;
      }
    } else if (s.current_index < 0) {
      // Playlist emptied: stop and reset.
      loadedIndex = -1;
      loadedSig = "";
    }

    // Volume + mute come from the desktop's persisted settings, applied to
    // the <audio> element (skip while the user is dragging the slider).
    if (!volDragging) {
      $("vol").value = s.volume;
      $("volVal").textContent = s.volume;
      userVolume = Math.max(0, Math.min(1, s.volume / 100));
      audio.volume = userVolume;
    }
    // While this browser is the audio source (claimed), the desktop backend
    // is intentionally muted -- that is NOT the browser's mute state. Ignore
    // the desktop's mute here and keep the local <audio> as the source of
    // truth. Also ignore it while a claim is in flight (claimPending), to
    // avoid a race where a poll arriving mid-claim latches the desktop's mute
    // onto <audio> and never clears it. Only mirror the desktop mute when we
    // are plainly the controller (no claim held or pending).
    if (!claimed && !claimPending) {
      muted = !!s.muted;
      audio.muted = muted;
    } else {
      muted = audio.muted;
    }
    try {
      console.log("[remote] applyState mute: claimed=" + claimed +
        " claimPending=" + claimPending + " s.muted=" + s.muted +
        " -> audio.muted=" + audio.muted +
        " | remote_mode=" + s.remote_mode + " s.state=" + s.state +
        " s.pos=" + s.position_ms + " s.len=" + s.length_ms +
        " s.idx=" + s.current_index);
    } catch (e) {}
    updateMuteButton();

    $("btnShuffle").classList.toggle("toggled", !!s.shuffle);
    var rep = s.repeat || "none";
    var repBtn = $("btnRepeat");
    repBtn.classList.toggle("toggled", rep !== "none");
    repBtn.textContent = rep === "one" ? "🔂 Repeat 1"
                        : rep === "all" ? "🔁 Repeat All"
                        : "🔁 Repeat";
    highlightPlaying(s.current_index);
    updateNowCover(cur, s.current_index);

    // Keep the claim UI in sync with the desktop. If the server expired our
    // claim (e.g. our heartbeat lapsed and it reclaimed audio), reflect that.
    if (claimed && s.remote_mode === false) {
      claimed = false;
      audio.pause();
      updateListenButton();
      setListenNote("Another device took over, or the claim expired.", true);
    }
    // When we are not the audio source, mirror the desktop's play state and
    // playback position on the UI (we don't drive a local <audio> then, so
    // updateProgress -- which reads <audio> -- won't reflect the desktop).
    if (!claimed) {
      $("btnPlay").textContent = (s.state === "playing") ? "⏸" : "▶";
      if (!seeking) {
        var dpos = Math.max(0, s.position_ms | 0);
        var dlen = Math.max(0, s.length_ms | 0);
        $("seek").value = dlen > 0 ? Math.round((dpos / dlen) * 1000) : 0;
        $("curTime").textContent = fmt(dpos);
        $("durTime").textContent = fmt(dlen);
      }
      try {
        console.log("[remote] applyState progress (desktop source): pos=" +
          s.position_ms + " len=" + s.length_ms + " state=" + s.state);
      } catch (e) {}
    }
  }

  function updateNowCover(cur, idx) {
    var img = $("nowCover");
    if (cur && cur.has_cover && idx >= 0) {
      // Key the <img> by the track *identity*, not the index: a playlist
      // reorder/trim can keep the same index while the underlying track (and
      // thus its art) changes. The `t=` query only changes when the identity
      // changes, so the browser does not refetch on every poll, but it also
      // can never show a stale cover for a reused index.
      var sig = trackSig(cur);
      if (img.getAttribute("data-sig") !== sig) {
        img.setAttribute("data-sig", sig);
        img.src = "/api/cover/" + idx + "?t=" + encodeURIComponent(sig);
      }
      img.classList.add("show");
    } else {
      img.classList.remove("show");
      img.removeAttribute("src");
      img.removeAttribute("data-sig");
    }
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
    var sig = pl.count + ":" + pl.tracks.map(function (t) {
      return trackSig(t) + (t.has_cover ? "*" : "");
    }).join("|");
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
      var thumb = null;
      if (t.has_cover) {
        thumb = document.createElement("img");
        thumb.className = "thumb";
        thumb.alt = "";
        thumb.src = "/api/cover/" + t.index + "?t=" + encodeURIComponent(trackSig(t));
      }
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
      var del = document.createElement("button");
      del.className = "del";
      del.setAttribute("title", "Remove from playlist");
      del.setAttribute("aria-label", "Remove");
      del.textContent = "✕";
      del.addEventListener("click", function (ev) {
        // Don't let the row's click handler start playback.
        ev.stopPropagation();
        post("/api/remove", { index: t.index });
      });
      row.appendChild(idx);
      if (thumb) row.appendChild(thumb);
      row.appendChild(meta);
      row.appendChild(dur);
      row.appendChild(del);
      row.addEventListener("click", function () {
        // Select on the desktop (sets current_index, load-only) and load the
        // audio immediately in the browser without waiting for the next poll.
        loadIndex(t.index, true, trackSig(t));
        post("/api/play", { index: t.index });
      });
      list.appendChild(row);
    });
  }

  // -- wiring --
  $("btnPlay").addEventListener("click", togglePlay);
  $("btnPrev").addEventListener("click", function () { command("previous"); });
  $("btnNext").addEventListener("click", function () { command("next"); });
  $("btnStop").addEventListener("click", function () {
    audio.pause();
    audio.currentTime = 0;
    reportState();
    command("stop");
  });
  $("btnVolUp").addEventListener("click", function () { command("volume_up"); });
  $("btnVolDown").addEventListener("click", function () { command("volume_down"); });
  $("btnMute").addEventListener("click", function () {
    muted = !muted;
    audio.muted = muted;
    updateMuteButton();
    // When this browser owns the audio, the desktop stays muted regardless
    // (remote mode); toggling its mute would leak sound from the desktop.
    // Only forward the mute command when the desktop is the audio source.
    if (!claimed) {
      command("mute");
    }
  });
  $("btnShuffle").addEventListener("click", function () { command("toggle_shuffle"); });
  $("btnRepeat").addEventListener("click", function () { command("cycle_repeat"); });
  $("btnListen").addEventListener("click", toggleListen);

  // Relinquish the audio claim when the page goes away so the desktop
  // reclaims its own audio promptly (the server also expires stale claims).
  window.addEventListener("pagehide", function () { if (claimed) releaseAudio(true); });
  window.addEventListener("beforeunload", function () { if (claimed) releaseAudio(true); });

  var seek = $("seek");
  seek.addEventListener("input", function () { seeking = true; });
  seek.addEventListener("change", function () {
    var fraction = Math.max(0, Math.min(1, (seek.value || 0) / 1000));
    if (claimed) {
      // Browser is the audio source: seek the local <audio>.
      var dur = isFinite(audio.duration) ? audio.duration : 0;
      if (dur > 0) { audio.currentTime = fraction * dur; }
      reportState();
    } else {
      // Desktop is the audio source: tell it to seek. Update the time label
      // optimistically; the next poll will reconcile from the desktop.
      post("/api/seek", { fraction: fraction });
      try { console.log("[remote] seek -> desktop fraction=" + fraction.toFixed(3)); } catch (e) {}
    }
    setTimeout(function () { seeking = false; }, 200);
  });

  var vol = $("vol");
  vol.addEventListener("input", function () {
    volDragging = true;
    $("volVal").textContent = vol.value;
    userVolume = Math.max(0, Math.min(1, vol.value / 100));
    audio.volume = userVolume;
  });
  vol.addEventListener("change", function () {
    post("/api/volume", { value: parseInt(vol.value, 10) });
    setTimeout(function () { volDragging = false; }, 400);
  });

  // -- polling loops --
  function pollState() {
    api("/api/state").then(applyState).catch(function () { setConn("bad"); });
  }
  function pollPlaylist() {
    api("/api/playlist").then(renderPlaylist).catch(function () {});
  }

  pollState();
  pollPlaylist();
  updateListenButton();
  updateMuteButton();
  setInterval(pollState, 1000);
  setInterval(pollPlaylist, 3000);
  // Report our playback position to the desktop a few times a second.
  setInterval(reportState, 1000);
})();
</script>
</body>
</html>
"""
