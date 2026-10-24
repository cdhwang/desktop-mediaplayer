"""Tests for the remote web page's audio-streaming integration.

``web.py`` is a single static HTML/JS string, so these are necessarily
string-level checks: they assert the page wires up the ``<audio>`` element,
references the audio-streaming and reverse-report endpoints, and keeps the
browser-as-source-of-truth control flow (follow ``current_index``, report
state, drive the ``<audio>`` element for transport).
"""

from __future__ import annotations

from desktop_music.services.remote.web import REMOTE_PAGE_HTML as HTML


def test_has_hidden_audio_element():
    assert '<audio id="audioEl"' in HTML
    assert "display:none" in HTML


def test_references_audio_stream_endpoint():
    assert '"/api/audio/" + index' in HTML


def test_reports_state_to_desktop():
    assert "/api/remote/state" in HTML
    assert "position_ms" in HTML
    assert "length_ms" in HTML


def test_follows_desktop_current_index():
    # The browser loads the matching audio whenever the polled index changes.
    assert "s.current_index !== loadedIndex" in HTML
    assert "loadIndex(" in HTML


def test_transport_drives_audio_element():
    assert "audio.play()" in HTML
    assert "audio.pause()" in HTML
    assert "audio.currentTime" in HTML
    assert "audio.volume" in HTML


def test_auto_advance_on_ended():
    assert 'audio.addEventListener("ended"' in HTML
    assert 'command("next")' in HTML


def test_track_click_loads_and_selects():
    assert 'post("/api/play", { index: t.index })' in HTML


def test_loading_indicator_present():
    assert "loading track" in HTML


# -- playlist deletion sync -----------------------------------------------


def test_has_per_track_delete_button():
    # A delete button is created per row and labelled.
    assert 'del.className = "del"' in HTML
    assert "Remove" in HTML


def test_delete_button_posts_remove_and_stops_propagation():
    assert 'post("/api/remove", { index: t.index })' in HTML
    assert "ev.stopPropagation()" in HTML


def test_follows_track_identity_not_index():
    # The browser compares a stable track signature, so an index shift from a
    # deletion does not restart the currently-playing track.
    assert "function trackSig(" in HTML
    assert "sig !== loadedSig" in HTML
    assert "loadedSig" in HTML


def test_index_shift_keeps_playing():
    # Same identity, new index -> update bookkeeping without reloading audio.
    assert "s.current_index !== loadedIndex" in HTML
    assert "loadedIndex = s.current_index" in HTML
