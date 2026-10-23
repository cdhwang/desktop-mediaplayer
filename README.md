# Desktop Music

A PotPlayer-style desktop media player built with **PyQt6** and **libVLC**
(python-vlc). Plays both audio and video, with a playlist, metadata/album
art, search, equalizer presets, lyrics, an offline spectrum visualizer,
full video support (fullscreen, tracks, external subtitles, speed,
snapshots), and fully customizable keyboard shortcuts.

## Features

- **Audio**: MP3 / FLAC / WAV — play/pause, seek, volume, mute
- **Video**: MP4 / MKV / AVI — in-window & fullscreen playback
- **Playlist**: add files/folders, double-click to play, auto-advance
- **Shuffle / Repeat**: none / all / one, persisted between sessions
- **Search**: filter by title / artist / album / filename
- **Metadata & album art**: extracted with mutagen
- **Equalizer**: libVLC built-in presets (Rock, Pop, Classical, …)
- **Audio compressor**: toggle libVLC's `compressor` dynamic range
  compressor on/off, persisted between sessions
- **Lyrics**: embedded tags (USLT / Vorbis) or a sidecar `.lrc` / `.txt`
- **Spectrum visualizer**: offline FFT analysis synced to playback
- **Video extras**: audio/subtitle track selection, external `.srt`
  subtitles, playback speed, frame snapshots
- **Customizable shortcuts**: reassign any command, conflict detection,
  restore defaults — all saved to disk
- **Web remote control**: control playback from any browser on the same
  Wi-Fi (play/pause, next/previous, volume, mute, shuffle/repeat, seek,
  pick a track) — no app install, served by the desktop itself
- **Dark theme**: PotPlayer-inspired QSS

## Requirements

- Linux with **libVLC** installed:
  ```bash
  sudo apt-get install vlc libvlc-dev
  ```
- **ffmpeg** (used for spectrum analysis and metadata decoding):
  ```bash
  sudo apt-get install ffmpeg
  ```
- **uv** for dependency management.

## Run

```bash
uv run python main.py
```

## Web remote control

Enable **Tools → Remote Control (web browser)** in the app. The desktop then
runs a small HTTP server on port **8787**. On a phone, tablet, or another
computer on the **same Wi-Fi**, open:

```
http://<desktop-ip>:8787/
```

(replace `<desktop-ip>` with the machine's LAN IP, e.g. `192.168.1.20`). The
page shows the playlist and the current track (with album art), and lets you
play/pause, skip, change volume, mute, toggle shuffle/repeat, seek, and tap a
track to play it. Album art is served per track and displayed both for the
now-playing item and as a thumbnail in the playlist. It refreshes by polling,
so no extra app or configuration is needed. There is no authentication, so
only enable it on networks you trust. The on/off choice is remembered between
sessions.

## Test

```bash
uv run pytest
```

## Layout

```
src/desktop_music/
  app.py              # QApplication bootstrap + dark theme
  constants.py        # supported formats, app metadata
  core/               # Qt-agnostic-ish logic
    commands.py       # named command registry (+ default shortcuts)
    controller.py     # PlayerController: backend <-> UI signals
    playlist.py       # PlaylistModel (QAbstractListModel)
    playlist_filter.py# search/filter proxy
    playmode.py       # shuffle / repeat logic
    shortcuts.py      # ShortcutManager
    formatting.py     # time formatting
  services/           # backend integrations
    backend.py        # VLCBackend (python-vlc wrapper)
    metadata.py       # mutagen tag/art extraction
    lyrics.py         # embedded + sidecar lyrics
    equalizer.py      # libVLC EQ presets
    spectrum.py       # offline FFT analysis
    settings.py       # JSON persistence
    remote/           # web remote control (same-LAN browser)
      remote_service.py # HTTP routes -> controller/playlist
      http_server.py  # minimal HTTP/1.1 on QTcpServer
      state.py        # controller/playlist -> JSON snapshots
      web.py          # single-file HTML remote page
  ui/                 # PyQt6 widgets
    main_window.py    # window, menu bar, wiring
    control_bar.py    # transport controls
    playlist_panel.py # playlist + search
    central_display.py# stacked: album art / spectrum / video / lyrics
    album_art_view.py, spectrum_widget.py, video_surface.py,
    lyrics_view.py, equalizer_dialog.py, shortcut_dialog.py, theme.py
  resources/          # bundled assets
    app_icon.svg      # source icon artwork
    app_icon*.png     # rendered sizes (16-256) + .ico
    render_icon.py    # regenerate PNGs from the SVG via QtSvg
```

State (playlist, volume, play mode, EQ preset, shortcuts, web-remote on/off)
is stored at `~/.config/desktop-music/state.json`.
