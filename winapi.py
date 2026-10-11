"""The Windows-only pieces: keyboard blocking, a global hotkey, media keys, start-with-Windows."""

import ctypes
import os
import queue
import subprocess
import sys
import threading
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_KEYBOARD_LL = 13
WM_QUIT = 0x0012
WM_HOTKEY = 0x0312
LLKHF_ALTDOWN = 0x20
VK_TAB, VK_ESCAPE, VK_F4 = 0x09, 0x1B, 0x73
VK_LWIN, VK_RWIN = 0x5B, 0x5C
VK_CONTROL = 0x11
VK_MEDIA_PLAY_PAUSE = 0xB3
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.GetAsyncKeyState.restype = ctypes.c_short
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def _message_loop():
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        yield msg
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


class KeyBlocker:
    """Low-level keyboard hook that swallows the shortcuts used to leave a window.

    Runs on its own thread with its own message loop so a busy Tk loop can never
    make Windows time the hook out.
    """

    def __init__(self):
        self._thread_id = None
        self._ready = threading.Event()
        self._proc = HOOKPROC(self._callback)  # keep a reference or ctypes frees it

    @staticmethod
    def should_block(vk, alt_down, ctrl_down):
        if vk in (VK_LWIN, VK_RWIN):
            return True
        if alt_down and vk in (VK_TAB, VK_ESCAPE, VK_F4):
            return True
        return vk == VK_ESCAPE and ctrl_down  # Ctrl+Esc, Ctrl+Shift+Esc

    def _callback(self, code, wparam, lparam):
        try:
            if code == 0:
                kb = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                ctrl = user32.GetAsyncKeyState(VK_CONTROL) & 0x8000
                if self.should_block(kb.vkCode, kb.flags & LLKHF_ALTDOWN, ctrl):
                    return 1
        except Exception:
            pass
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _run(self):
        self._thread_id = kernel32.GetCurrentThreadId()
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, kernel32.GetModuleHandleW(None), 0)
        self._ready.set()
        for _ in _message_loop():
            pass
        if hook:
            user32.UnhookWindowsHookEx(hook)

    def start(self):
        self._ready.clear()
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(2)

    def stop(self):
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread_id = None


class Hotkey:
    """Ctrl+Alt+<key> from anywhere (including a full-screen game), one hotkey per (key, name) pair.

    Each press lands in `self.presses` as its name. `ok` says which ones Windows let us register (another
    app may already own one).
    """

    def __init__(self, keys=(("U", "urge"),)):
        self.keys = list(keys)
        self.presses = queue.Queue()
        self.ok = {}
        self._ready = threading.Event()

    def _run(self):
        for i, (key, name) in enumerate(self.keys, start=1):
            self.ok[name] = bool(user32.RegisterHotKey(None, i, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord(key)))
        self._ready.set()
        if not any(self.ok.values()):
            return
        for msg in _message_loop():
            if msg.message == WM_HOTKEY and 1 <= int(msg.wParam) <= len(self.keys):
                self.presses.put(self.keys[int(msg.wParam) - 1][1])

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(2)
        return self.ok


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                     ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, MONITORENUMPROC, wintypes.LPARAM]
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]


def monitors():
    """Every connected monitor, numbered left to right."""
    from placement import Monitor, numbered

    found = []

    def cb(hmon, hdc, rect, lparam):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r, w = info.rcMonitor, info.rcWork
            found.append(Monitor(
                name=info.szDevice, x=r.left, y=r.top, w=r.right - r.left, h=r.bottom - r.top,
                work=(w.left, w.top, w.right - w.left, w.bottom - w.top), primary=bool(info.dwFlags & 1),
            ))
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    return numbered(found)


def virtual_screen():
    """Bounding box of every monitor: (x, y, width, height)."""
    g = user32.GetSystemMetrics
    return g(76), g(77), g(78), g(79)


def press_media_play():
    user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
    user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 2, 0)


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds():
    """Seconds since the last keyboard or mouse input, or None when Windows won't say."""
    info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


_instance = None


def single_instance(wait_seconds=0.0):
    """True if this is the only copy running. With wait_seconds, wait that long for an older copy to
    exit first - used by "Restart to update", where the new copy starts as the old one closes."""
    import time
    global _instance
    deadline = time.monotonic() + wait_seconds
    while True:
        handle = kernel32.CreateMutexW(None, False, "UrgeButtonSingleInstance")
        if ctypes.get_last_error() != 183:  # ERROR_ALREADY_EXISTS
            _instance = handle
            return True
        kernel32.CloseHandle(handle)
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.3)


def set_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass


# -- start with Windows: a shortcut in the user's Startup folder

STARTUP_LINK = (
    Path(os.environ.get("APPDATA", Path.home()))
    / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Urge Button.lnk"
)
SCRIPT = Path(__file__).resolve().parent / "urge_button.py"


def pythonw():
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.exists() else exe


def starts_with_windows():
    return STARTUP_LINK.exists()


def desktop_link():
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                          "[Environment]::GetFolderPath('Desktop')"],
                         capture_output=True, text=True, creationflags=0x08000000, check=False)
    return Path(out.stdout.strip() or Path.home() / "Desktop") / "Urge Button.lnk"


def set_start_with_windows(enabled):
    if not enabled:
        STARTUP_LINK.unlink(missing_ok=True)
        return True
    return make_shortcut(STARTUP_LINK)


def make_shortcut(link):
    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:URGE_LINK);"
        "$s.TargetPath = $env:URGE_EXE; $s.Arguments = '\"' + $env:URGE_SCRIPT + '\"';"
        "$s.WorkingDirectory = $env:URGE_DIR; $s.Save()"
    )
    env = dict(os.environ, URGE_LINK=str(link), URGE_EXE=str(pythonw()),
               URGE_SCRIPT=str(SCRIPT), URGE_DIR=str(SCRIPT.parent))
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                   env=env, creationflags=0x08000000, check=False)  # CREATE_NO_WINDOW
    return Path(link).exists()
