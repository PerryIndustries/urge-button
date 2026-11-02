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


HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, MONITOR_OFF = 0xFFFF, 0x0112, 0xF170, 2
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]


def monitors_off():
    """Every monitor goes dark now (the PC stays awake); any mouse move or key brings them back. Posted, not sent,
    so a hung window can't stall the caller."""
    user32.PostMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, MONITOR_OFF)


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


# --------------------------------------------------------------------------- tray icon

WM_DESTROY, WM_CLOSE = 0x0002, 0x0010
WM_LBUTTONUP, WM_RBUTTONUP = 0x0202, 0x0205
WM_TRAY = 0x8000 + 1  # WM_APP + 1
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON)]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.CreateIconFromResourceEx.argtypes = [ctypes.c_char_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
                                            ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.CreateIconFromResourceEx.restype = wintypes.HICON
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DestroyWindow.argtypes = [wintypes.HWND]
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL


def dot_icon_bytes(rgb, size=32):
    """An icon resource (BITMAPINFOHEADER + BGRA pixels + AND mask) for a soft-edged round dot of colour rgb."""
    import struct
    r0, g0, b0 = rgb
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, size * size * 4, 0, 0, 0, 0)
    c = (size - 1) / 2
    radius = size / 2 - 1.5
    pixels = bytearray()
    for y in range(size - 1, -1, -1):  # bottom-up rows
        for x in range(size):
            d = ((x - c) ** 2 + (y - c) ** 2) ** 0.5
            a = max(0.0, min(1.0, radius + 0.5 - d))
            pixels += bytes((round(b0 * a), round(g0 * a), round(r0 * a), round(255 * a)))  # premultiplied
    mask = bytes(size * size // 8)  # all zero: the alpha channel decides
    return header + bytes(pixels) + mask


class TrayIcon:
    """One icon in the notification area (Windows 11 puts a new one behind the ^ arrow).

    Runs its own hidden window and message loop on a thread. Clicks land in `self.clicks` as "left" or
    "right" for the Tk thread to pick up. Comes back by itself if Explorer restarts.
    """

    def __init__(self, tip="Urge Button", rgb=(0x6A, 0x75, 0xF7)):
        self.tip = tip
        self.rgb = rgb
        self.clicks = queue.Queue()
        self.hwnd = None
        self._ready = threading.Event()
        self._proc = WNDPROC(self._wndproc)  # keep a reference or ctypes frees it
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        self._icon = None

    def _data(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self._icon
        nid.szTip = self.tip[:127]
        return nid

    def _add(self):
        return bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._data())))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            event = lparam & 0xFFFF
            if event == WM_LBUTTONUP:
                self.clicks.put("left")
            elif event == WM_RBUTTONUP:
                self.clicks.put("right")
            return 0
        if msg == self._taskbar_created:
            self._add()
            return 0
        if msg == WM_CLOSE:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._data()))
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self):
        try:
            hinst = kernel32.GetModuleHandleW(None)
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = self._proc
            wc.hInstance = hinst
            wc.lpszClassName = "UrgeButtonTray"
            user32.RegisterClassExW(ctypes.byref(wc))
            # A plain hidden window (not message-only) so it hears the TaskbarCreated broadcast.
            self.hwnd = user32.CreateWindowExW(0, "UrgeButtonTray", "Urge Button tray", 0, 0, 0, 0, 0,
                                               None, None, hinst, None)
            data = dot_icon_bytes(self.rgb)
            self._icon = user32.CreateIconFromResourceEx(data, len(data), True, 0x00030000, 32, 32, 0)
            ok = bool(self.hwnd) and self._add()
        except (OSError, ValueError):
            ok = False
        self.ok = ok
        self._ready.set()
        if not self.hwnd:
            return
        for _ in _message_loop():
            pass

    def start(self):
        self.ok = False
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(3)
        return self.ok

    def stop(self):
        """Take the icon away now (any thread may call Shell_NotifyIcon), then end the tray thread."""
        if self.hwnd:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._data()))
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
