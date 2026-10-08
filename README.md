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
- **Lyrics**: embedded tags (USLT / Vorbis) or a sidecar `.lrc` / `.txt`
- **Spectrum visualizer**: offline FFT analysis synced to playback
- **Video extras**: audio/subtitle track selection, external `.srt`
  subtitles, playback speed, frame snapshots
- **Customizable shortcuts**: reassign any command, conflict detection,
  restore defaults — all saved to disk
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

State (playlist, volume, play mode, EQ preset, shortcuts) is stored at
`~/.config/desktop-music/state.json`.
