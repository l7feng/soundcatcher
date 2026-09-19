"""截取"正在运行的" SoundCatcher 主窗口并存为 PNG。

与 screenshot_gui.py 不同：本脚本**不新建实例**，而是抓取已打开的真实窗口，
用于让用户/开发者看到当前界面实况。

用法::

    python scripts/capture_live_window.py [输出.png] [窗口标题关键字]
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

SW_RESTORE = 9
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def find_window(keyword: str) -> int:
    found: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
        if keyword.lower() in title.lower():
            found.append((hwnd, title))
        return True

    user32.EnumWindows(cb, 0)
    if not found:
        return 0
    # 取面积最大的（主窗口）
    best, best_area = 0, -1
    for hwnd, _t in found:
        r = RECT()
        user32.GetClientRect(hwnd, ctypes.byref(r))
        area = (r.right - r.left) * (r.bottom - r.top)
        if area > best_area:
            best, best_area = hwnd, area
    return best


def capture(hwnd: int, out: Path) -> tuple[int, int]:
    user32.SetForegroundWindow(hwnd)
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    r = RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        raise RuntimeError(f"窗口尺寸异常 {w}x{h}")

    hdc = user32.GetDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(memdc, bmp)

    # PW_CLIENTONLY
    user32.PrintWindow(hwnd, memdc, 1)

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h  # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0

    bufsize = w * h * 4
    buf = ctypes.create_string_buffer(bufsize)
    got = gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(bmi), DIB_RGB_COLORS)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(hwnd, hdc)

    if got == 0:
        raise RuntimeError("GetDIBits 失败")

    # 用 Qt 写 PNG（venv 内已有 PySide6，避免额外依赖）
    from PySide6.QtGui import QImage
    img = QImage(bytes(buf), w, h, w * 4, QImage.Format.Format_RGB32)
    img.save(str(out))
    return w, h


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT / "data-test" / "live-window.png"
    keyword = sys.argv[2] if len(sys.argv) > 2 else "SoundCatcher"
    hwnd = find_window(keyword)
    if not hwnd:
        print(f"[FAIL] 未找到标题含 {keyword!r} 的可见窗口")
        return 1
    w, h = capture(hwnd, out)
    print(f"[OK] hwnd={hwnd} -> {out} ({w}x{h})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
