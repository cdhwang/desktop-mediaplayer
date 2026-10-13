"""Windows taskbar button overlay icons.

Windows lets an application composite a small badge onto the lower-right
corner of its taskbar button via the shell ``ITaskbarList3::SetOverlayIcon``
COM method. We use it to reflect playback state (play / pause) on the taskbar
without disturbing the base application icon.

PyQt6 dropped the ``QtWinExtras`` module that used to wrap this, so the COM
call is made directly through :mod:`ctypes`. Everything here is a safe no-op
on non-Windows platforms (and whenever the COM calls fail), so callers can
invoke it unconditionally.

Typical use::

    overlay = TaskbarOverlay()
    overlay.set_window(main_window.winId())
    overlay.set_overlay(play_icon, "Playing")
    overlay.clear()
"""

from __future__ import annotations

import sys

_IS_WINDOWS = sys.platform == "win32"


def set_app_user_model_id(app_id: str) -> None:
    """Set an explicit AppUserModelID for this process (Windows only).

    Windows groups taskbar buttons and attaches taskbar features (overlay
    icons, jump lists, thumbnails) by a process's AppUserModelID. A GUI app
    launched through the Python interpreter would otherwise inherit the host
    process's identity, which can prevent the taskbar overlay from appearing
    on the right button. Giving the process a stable, explicit ID fixes that.

    No-op on non-Windows platforms and on any failure.
    """
    if not _IS_WINDOWS:
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (OSError, AttributeError):
        pass


class TaskbarOverlay:
    """Manages the taskbar button overlay icon for a single window.

    On non-Windows platforms every method is a no-op. On Windows the first
    successful :meth:`set_window` lazily creates the ``ITaskbarList3`` COM
    object; failures are swallowed so a missing/old shell never breaks the UI.
    """

    def __init__(self) -> None:
        self._hwnd: int | None = None
        self._taskbar = None  # ITaskbarList3 vtable wrapper (Windows only)
        self._initialized = False
        self._available = _IS_WINDOWS

    # -- public API --------------------------------------------------------

    def set_window(self, win_id) -> None:
        """Bind this helper to a top-level window handle (``QWidget.winId()``)."""
        if not self._available:
            return
        try:
            self._hwnd = int(win_id)
        except (TypeError, ValueError):
            self._hwnd = None

    def set_overlay(self, icon, description: str = "") -> None:
        """Show *icon* (a ``QIcon``) as the taskbar overlay badge.

        A null/empty icon clears any existing overlay.
        """
        if not self._available or self._hwnd is None:
            return
        if icon is None or icon.isNull():
            self.clear(description)
            return
        hicon = _qicon_to_hicon(icon)
        if not hicon:
            return
        try:
            self._apply(hicon, description)
        finally:
            # SetOverlayIcon copies the icon, so we own and must free ours.
            _destroy_icon(hicon)

    def clear(self, description: str = "") -> None:
        """Remove any taskbar overlay badge."""
        if not self._available or self._hwnd is None:
            return
        self._apply(0, description)

    # -- internals ---------------------------------------------------------

    def _apply(self, hicon: int, description: str) -> None:
        if not self._ensure_taskbar():
            return
        try:
            self._taskbar.SetOverlayIcon(self._hwnd, hicon, description)
        except OSError:
            # Shell can intermittently reject the call (e.g. invalid handle);
            # treat as a non-fatal cosmetic failure.
            pass

    def _ensure_taskbar(self) -> bool:
        if self._taskbar is not None:
            return True
        if self._initialized:
            return False
        self._initialized = True
        try:
            self._taskbar = _create_taskbar_list()
        except OSError:
            self._taskbar = None
        return self._taskbar is not None


# ---------------------------------------------------------------------------
# Windows-only implementation details. Imported lazily so this module stays
# importable (as a no-op) on every platform.
# ---------------------------------------------------------------------------

if _IS_WINDOWS:  # pragma: no cover - exercised only on Windows
    import ctypes
    from ctypes import POINTER, byref, c_void_p
    from ctypes.wintypes import (
        BOOL,
        BYTE,
        DWORD,
        HICON,
        HWND,
        LONG,
        LPCWSTR,
        WORD,
    )

    ole32 = ctypes.oledll.ole32
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    class GUID(ctypes.Structure):
        """Minimal self-contained GUID so we avoid a comtypes dependency."""

        _fields_ = [
            ("Data1", DWORD),
            ("Data2", WORD),
            ("Data3", WORD),
            ("Data4", BYTE * 8),
        ]

        def __init__(self, guid: str) -> None:
            super().__init__()
            # Parse "{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}".
            s = guid.strip("{}")
            parts = s.split("-")
            self.Data1 = int(parts[0], 16)
            self.Data2 = int(parts[1], 16)
            self.Data3 = int(parts[2], 16)
            rest = parts[3] + parts[4]
            for i in range(8):
                self.Data4[i] = int(rest[i * 2 : i * 2 + 2], 16)

    # CLSID_TaskbarList / IID_ITaskbarList3
    _CLSID_TaskbarList = GUID("{56FDF344-FD6D-11D0-958A-006097C9A090}")
    _IID_ITaskbarList3 = GUID("{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}")

    CLSCTX_INPROC_SERVER = 0x1
    HRESULT = ctypes.c_long

    class _ITaskbarList3VTable(ctypes.Structure):
        """Only the slots up to SetOverlayIcon, in vtable order."""

        _fields_ = [
            # IUnknown
            ("QueryInterface", ctypes.c_void_p),
            ("AddRef", ctypes.c_void_p),
            ("Release", ctypes.c_void_p),
            # ITaskbarList
            ("HrInit", ctypes.c_void_p),
            ("AddTab", ctypes.c_void_p),
            ("DeleteTab", ctypes.c_void_p),
            ("ActivateTab", ctypes.c_void_p),
            ("SetActiveAlt", ctypes.c_void_p),
            # ITaskbarList2
            ("MarkFullscreenWindow", ctypes.c_void_p),
            # ITaskbarList3
            ("SetProgressValue", ctypes.c_void_p),
            ("SetProgressState", ctypes.c_void_p),
            ("RegisterTab", ctypes.c_void_p),
            ("UnregisterTab", ctypes.c_void_p),
            ("SetTabOrder", ctypes.c_void_p),
            ("SetTabActive", ctypes.c_void_p),
            ("ThumbBarAddButtons", ctypes.c_void_p),
            ("ThumbBarUpdateButtons", ctypes.c_void_p),
            ("ThumbBarSetImageList", ctypes.c_void_p),
            ("SetOverlayIcon", ctypes.c_void_p),
            ("SetThumbnailTooltip", ctypes.c_void_p),
            ("SetThumbnailClip", ctypes.c_void_p),
        ]

    class _ITaskbarList3(ctypes.Structure):
        _fields_ = [("lpVtbl", POINTER(_ITaskbarList3VTable))]

    # Prototypes for the two vtable methods we actually invoke.
    _HrInit_t = ctypes.WINFUNCTYPE(HRESULT, c_void_p)
    _Release_t = ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)
    _SetOverlayIcon_t = ctypes.WINFUNCTYPE(HRESULT, c_void_p, HWND, HICON, LPCWSTR)

    class _TaskbarList:
        """Thin wrapper exposing SetOverlayIcon on a live COM pointer."""

        def __init__(self, ptr):
            self._ptr = ptr  # POINTER(_ITaskbarList3)
            vtbl = ptr.contents.lpVtbl.contents
            self._set_overlay = _SetOverlayIcon_t(vtbl.SetOverlayIcon)
            self._release = _Release_t(vtbl.Release)

        def SetOverlayIcon(self, hwnd: int, hicon: int, description: str) -> None:
            hr = self._set_overlay(
                self._ptr, HWND(hwnd), HICON(hicon), description or None
            )
            if hr < 0:
                raise OSError(f"SetOverlayIcon failed: 0x{hr & 0xFFFFFFFF:08X}")

        def __del__(self):
            try:
                if getattr(self, "_ptr", None):
                    self._release(self._ptr)
            except Exception:
                pass

    def _create_taskbar_list():
        """CoCreateInstance the shell TaskbarList and call HrInit()."""
        try:
            ole32.CoInitialize(None)
        except OSError:
            pass  # already initialized on this thread
        ptr = POINTER(_ITaskbarList3)()
        ole32.CoCreateInstance(
            byref(_CLSID_TaskbarList),
            None,
            CLSCTX_INPROC_SERVER,
            byref(_IID_ITaskbarList3),
            byref(ptr),
        )
        vtbl = ptr.contents.lpVtbl.contents
        hr_init = _HrInit_t(vtbl.HrInit)
        hr = hr_init(ptr)
        if hr < 0:
            raise OSError(f"ITaskbarList3::HrInit failed: 0x{hr & 0xFFFFFFFF:08X}")
        return _TaskbarList(ptr)

    # ---- QIcon -> HICON ---------------------------------------------------

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", DWORD),
            ("biWidth", LONG),
            ("biHeight", LONG),
            ("biPlanes", WORD),
            ("biBitCount", WORD),
            ("biCompression", DWORD),
            ("biSizeImage", DWORD),
            ("biXPelsPerMeter", LONG),
            ("biYPelsPerMeter", LONG),
            ("biClrUsed", DWORD),
            ("biClrImportant", DWORD),
        ]

    class _BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", DWORD * 1)]

    class _ICONINFO(ctypes.Structure):
        _fields_ = [
            ("fIcon", BOOL),
            ("xHotspot", DWORD),
            ("yHotspot", DWORD),
            ("hbmMask", c_void_p),
            ("hbmColor", c_void_p),
        ]

    _BI_RGB = 0
    _DIB_RGB_COLORS = 0

    user32.CreateIconIndirect.restype = HICON
    user32.CreateIconIndirect.argtypes = [POINTER(_ICONINFO)]
    user32.DestroyIcon.argtypes = [HICON]
    user32.DestroyIcon.restype = BOOL
    gdi32.CreateDIBSection.restype = c_void_p
    gdi32.CreateBitmap.restype = c_void_p
    gdi32.DeleteObject.argtypes = [c_void_p]

    def _qicon_to_hicon(icon, size: int = 16) -> int:
        """Convert a QIcon to a Windows HICON (32bpp premultiplied ARGB).

        Returns 0 on failure. The caller owns the result and must free it with
        :func:`_destroy_icon`.
        """
        from PyQt6.QtCore import QSize, Qt
        from PyQt6.QtGui import QImage

        pixmap = icon.pixmap(QSize(size, size))
        if pixmap.isNull():
            return 0
        image = pixmap.toImage().convertToFormat(
            QImage.Format.Format_ARGB32_Premultiplied
        )
        w, h = image.width(), image.height()
        if w <= 0 or h <= 0:
            return 0

        # Build a top-down 32bpp DIB and copy the BGRA pixels into it.
        bmi = _BITMAPINFO()
        hdr = bmi.bmiHeader
        hdr.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        hdr.biWidth = w
        hdr.biHeight = -h  # negative => top-down
        hdr.biPlanes = 1
        hdr.biBitCount = 32
        hdr.biCompression = _BI_RGB

        bits = c_void_p()
        hbm_color = gdi32.CreateDIBSection(
            None, byref(bmi), _DIB_RGB_COLORS, byref(bits), None, 0
        )
        if not hbm_color or not bits:
            if hbm_color:
                gdi32.DeleteObject(hbm_color)
            return 0

        # QImage ARGB32 is already BGRA in memory on little-endian Windows,
        # matching the DIB's expected byte order.
        ptr = image.constBits()
        ptr.setsize(image.sizeInBytes())
        ctypes.memmove(bits, bytes(ptr), min(image.sizeInBytes(), w * h * 4))

        # Monochrome mask bitmap (unused for 32bpp alpha icons but required).
        hbm_mask = gdi32.CreateBitmap(w, h, 1, 1, None)
        if not hbm_mask:
            gdi32.DeleteObject(hbm_color)
            return 0

        info = _ICONINFO()
        info.fIcon = True
        info.xHotspot = 0
        info.yHotspot = 0
        info.hbmMask = hbm_mask
        info.hbmColor = hbm_color
        hicon = user32.CreateIconIndirect(byref(info))

        gdi32.DeleteObject(hbm_color)
        gdi32.DeleteObject(hbm_mask)
        return int(hicon) if hicon else 0

    def _destroy_icon(hicon: int) -> None:
        if hicon:
            user32.DestroyIcon(HICON(hicon))

else:  # non-Windows: provide inert stubs so the module imports cleanly.

    def _create_taskbar_list():  # type: ignore[misc]
        raise OSError("taskbar overlay is only available on Windows")

    def _qicon_to_hicon(icon, size: int = 16) -> int:  # type: ignore[misc]
        return 0

    def _destroy_icon(hicon: int) -> None:  # type: ignore[misc]
        return None
