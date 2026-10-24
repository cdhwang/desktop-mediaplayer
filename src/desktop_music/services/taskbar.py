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

import os
import sys

_IS_WINDOWS = sys.platform == "win32"

# Name of the GUI launcher executable generated from pyproject's
# ``[project.gui-scripts] desktop-music`` entry. Windows resolves the
# "Open with" menu's icon/name from this executable's ``Applications``
# registration, so we prefer it as both the shortcut target and the
# file-association command.
_LAUNCHER_EXE = "desktop-music.exe"


def find_app_launcher() -> str:
    """Return the path to the app's dedicated GUI launcher exe, or "".

    Looks for ``desktop-music.exe`` (the ``[project.gui-scripts]`` console
    launcher) next to the running interpreter and in common venv/user-base
    ``Scripts`` locations. Returns an empty string when it can't be found
    (e.g. running from a source checkout that was never ``pip install``-ed),
    in which case callers fall back to launching via ``python -m``.
    """
    if not _IS_WINDOWS:
        return ""
    candidates = []
    exe_dir = os.path.dirname(sys.executable)
    candidates.append(os.path.join(exe_dir, _LAUNCHER_EXE))
    candidates.append(os.path.join(exe_dir, "Scripts", _LAUNCHER_EXE))
    candidates.append(os.path.join(sys.prefix, "Scripts", _LAUNCHER_EXE))
    # ``pip install --user`` script location.
    try:
        import site

        user_base = getattr(site, "getuserbase", lambda: "")()
        if user_base:
            candidates.append(
                os.path.join(user_base, "Scripts", _LAUNCHER_EXE)
            )
    except Exception:  # noqa: BLE001
        pass
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return ""


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


def ensure_app_shortcut(
    app_id: str,
    display_name: str,
    icon_path: str = "",
) -> None:
    """Create a Start-menu shortcut bound to *app_id* (Windows only).

    Windows resolves the taskbar / jump-list **display name and icon** from a
    Start-menu shortcut (``.lnk``) whose ``System.AppUserModel.ID`` property
    equals the running process's AppUserModelID. Without such a shortcut the
    jump list falls back to the launching executable, which for a ``uv``/
    ``python`` launch shows "python" and the generic Python icon.

    This creates (once) a shortcut at
    ``%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\<display_name>.lnk``
    pointing at the current interpreter, with:

    * its name set to *display_name* (what the jump-list header shows),
    * its icon set to *icon_path* (the ``.ico``), and
    * ``System.AppUserModel.ID`` set to *app_id* so Windows matches it to the
      process set up by :func:`set_app_user_model_id`.

    No-op on non-Windows platforms, when the shortcut already exists, and on
    any COM failure (purely cosmetic -- the app still runs).
    """
    if not _IS_WINDOWS:
        return
    try:
        _ensure_app_shortcut_win(app_id, display_name, icon_path)
    except Exception:  # noqa: BLE001 - cosmetic only, never break startup
        pass


def ensure_file_association_icon(
    display_name: str,
    icon_path: str = "",
) -> None:
    """Deprecated no-op kept for backward compatibility.

    File-type association (the Explorer "Open with" entry, its icon, and the
    per-type file icons) is handled entirely by the explicit, user-run
    ``scripts/register_windows.ps1`` so there is a single source of truth and
    no duplicate handlers. Registering it again here at every startup created
    a second "Desktop Music" entry that conflicted with the ProgID handlers
    the script installs, so the app no longer touches file associations.
    """
    return None


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

    # ---- Start-menu shortcut (jump-list name/icon) ------------------------
    #
    # Windows reads the taskbar/jump-list display name and icon from a
    # Start-menu .lnk whose System.AppUserModel.ID matches the process's
    # AppUserModelID. We create that .lnk via IShellLinkW + IPersistFile, and
    # stamp the AppUserModel.ID with IPropertyStore.

    import os as _os
    from ctypes import c_int, c_ulong, c_wchar_p, c_ushort, c_ubyte, c_ulonglong

    _CLSID_ShellLink = GUID("{00021401-0000-0000-C000-000000000046}")
    _IID_IShellLinkW = GUID("{000214F9-0000-0000-C000-000000000046}")
    _IID_IPersistFile = GUID("{0000010B-0000-0000-C000-000000000046}")
    _IID_IPropertyStore = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")

    # PROPERTYKEY for System.AppUserModel.ID.
    class _PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", DWORD)]

    _PKEY_AppUserModel_ID = _PROPERTYKEY()
    _PKEY_AppUserModel_ID.fmtid = GUID("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}")
    _PKEY_AppUserModel_ID.pid = 5

    # Minimal PROPVARIANT: a VT tag plus a pointer to a wide string (VT_LPWSTR).
    VT_LPWSTR = 31

    class _PROPVARIANT(ctypes.Structure):
        _fields_ = [
            ("vt", c_ushort),
            ("wReserved1", c_ushort),
            ("wReserved2", c_ushort),
            ("wReserved3", c_ushort),
            ("pwszVal", c_wchar_p),
            ("padding", c_ulonglong),
        ]

    # IShellLinkW vtable slots we use (IUnknown + the SetPath/SetIconLocation).
    class _IShellLinkWVTable(ctypes.Structure):
        _fields_ = [
            ("QueryInterface", c_void_p),
            ("AddRef", c_void_p),
            ("Release", c_void_p),
            ("GetPath", c_void_p),
            ("GetIDList", c_void_p),
            ("SetIDList", c_void_p),
            ("GetDescription", c_void_p),
            ("SetDescription", c_void_p),
            ("GetWorkingDirectory", c_void_p),
            ("SetWorkingDirectory", c_void_p),
            ("GetArguments", c_void_p),
            ("SetArguments", c_void_p),
            ("GetHotkey", c_void_p),
            ("SetHotkey", c_void_p),
            ("GetShowCmd", c_void_p),
            ("SetShowCmd", c_void_p),
            ("GetIconLocation", c_void_p),
            ("SetIconLocation", c_void_p),
            ("SetRelativePath", c_void_p),
            ("Resolve", c_void_p),
            ("SetPath", c_void_p),
        ]

    class _IShellLinkW(ctypes.Structure):
        _fields_ = [("lpVtbl", POINTER(_IShellLinkWVTable))]

    class _IPersistFileVTable(ctypes.Structure):
        _fields_ = [
            ("QueryInterface", c_void_p),
            ("AddRef", c_void_p),
            ("Release", c_void_p),
            ("GetClassID", c_void_p),
            ("IsDirty", c_void_p),
            ("Load", c_void_p),
            ("Save", c_void_p),
            ("SaveCompleted", c_void_p),
            ("GetCurFile", c_void_p),
        ]

    class _IPersistFile(ctypes.Structure):
        _fields_ = [("lpVtbl", POINTER(_IPersistFileVTable))]

    class _IPropertyStoreVTable(ctypes.Structure):
        _fields_ = [
            ("QueryInterface", c_void_p),
            ("AddRef", c_void_p),
            ("Release", c_void_p),
            ("GetCount", c_void_p),
            ("GetAt", c_void_p),
            ("GetValue", c_void_p),
            ("SetValue", c_void_p),
            ("Commit", c_void_p),
        ]

    class _IPropertyStore(ctypes.Structure):
        _fields_ = [("lpVtbl", POINTER(_IPropertyStoreVTable))]

    # Method prototypes (all WINFUNCTYPE / __stdcall).
    _QI_t = ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_void_p, c_void_p)
    _Rel_t = ctypes.WINFUNCTYPE(c_ulong, c_void_p)
    _SetStr_t = ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_wchar_p)
    _SetIcon_t = ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_wchar_p, c_int)
    _Save_t = ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_wchar_p, BOOL)
    _SetValue_t = ctypes.WINFUNCTYPE(
        HRESULT, c_void_p, POINTER(_PROPERTYKEY), POINTER(_PROPVARIANT)
    )
    _Commit_t = ctypes.WINFUNCTYPE(HRESULT, c_void_p)

    def _start_menu_programs_dir() -> str:
        """Return %APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs."""
        appdata = _os.environ.get("APPDATA", "")
        return _os.path.join(
            appdata, "Microsoft", "Windows", "Start Menu", "Programs"
        )

    def _ensure_app_shortcut_win(
        app_id: str, display_name: str, icon_path: str
    ) -> None:
        programs = _start_menu_programs_dir()
        if not programs:
            return
        lnk_path = _os.path.join(programs, f"{display_name}.lnk")
        if _os.path.exists(lnk_path):
            return  # already created in a previous run
        _os.makedirs(programs, exist_ok=True)

        try:
            ole32.CoInitialize(None)
        except OSError:
            pass

        # Create the IShellLinkW COM object.
        link = POINTER(_IShellLinkW)()
        ole32.CoCreateInstance(
            byref(_CLSID_ShellLink),
            None,
            CLSCTX_INPROC_SERVER,
            byref(_IID_IShellLinkW),
            byref(link),
        )
        sl_vtbl = link.contents.lpVtbl.contents
        sl_release = _Rel_t(sl_vtbl.Release)

        try:
            import sys as _sys

            # Prefer the app's dedicated GUI launcher (desktop-music.exe):
            # Windows then shows our name/icon in the "Open with" menu and the
            # shortcut has no visible console. Fall back to pythonw -m when the
            # launcher isn't installed (source checkout).
            launcher = find_app_launcher()
            if launcher:
                target = launcher
                args = ""
            else:
                target = _sys.executable
                pythonw = _os.path.join(_os.path.dirname(target), "pythonw.exe")
                if _os.path.exists(pythonw):
                    target = pythonw
                args = "-m desktop_music"

            set_path = _SetStr_t(sl_vtbl.SetPath)
            set_path(link, target)

            # Launch arguments (empty when targeting the dedicated launcher).
            set_args = _SetStr_t(sl_vtbl.SetArguments)
            set_args(link, args)

            set_wd = _SetStr_t(sl_vtbl.SetWorkingDirectory)
            set_wd(link, _os.path.dirname(target))

            if icon_path and _os.path.exists(icon_path):
                set_icon = _SetIcon_t(sl_vtbl.SetIconLocation)
                set_icon(link, icon_path, 0)

            set_desc = _SetStr_t(sl_vtbl.SetDescription)
            set_desc(link, display_name)

            # Stamp System.AppUserModel.ID via IPropertyStore.
            store = POINTER(_IPropertyStore)()
            qi = _QI_t(sl_vtbl.QueryInterface)
            if qi(link, byref(_IID_IPropertyStore), byref(store)) >= 0:
                ps_vtbl = store.contents.lpVtbl.contents
                pv = _PROPVARIANT()
                pv.vt = VT_LPWSTR
                pv.pwszVal = app_id
                set_value = _SetValue_t(ps_vtbl.SetValue)
                set_value(store, byref(_PKEY_AppUserModel_ID), byref(pv))
                commit = _Commit_t(ps_vtbl.Commit)
                commit(store)
                ps_release = _Rel_t(ps_vtbl.Release)
                ps_release(store)

            # Persist the .lnk to disk via IPersistFile::Save.
            persist = POINTER(_IPersistFile)()
            qi2 = _QI_t(sl_vtbl.QueryInterface)
            if qi2(link, byref(_IID_IPersistFile), byref(persist)) >= 0:
                pf_vtbl = persist.contents.lpVtbl.contents
                save = _Save_t(pf_vtbl.Save)
                save(persist, lnk_path, True)
                pf_release = _Rel_t(pf_vtbl.Release)
                pf_release(persist)
        finally:
            sl_release(link)

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

    def _ensure_app_shortcut_win(  # type: ignore[misc]
        app_id: str, display_name: str, icon_path: str
    ) -> None:
        return None

    def _qicon_to_hicon(icon, size: int = 16) -> int:  # type: ignore[misc]
        return 0

    def _destroy_icon(hicon: int) -> None:  # type: ignore[misc]
        return None
