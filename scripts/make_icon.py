"""生成 SoundCatcher 应用图标（assets/icon.ico + icon.png），零新增依赖。

用 Qt 自己画（QPainter）+ 自己写 ICO 容器（PNG 帧打包），避免为此引入 Pillow。
图形语义：深色圆角底 + 声波柱状 + 右下角放大镜（"抓声音"＝SoundCatcher）。

用法::

    .venv/Scripts/python.exe scripts/make_icon.py
    .venv/Scripts/python.exe scripts/make_icon.py --force   # 覆盖已存在
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT / "src" / "soundcatcher" / "gui" / "assets"

sys.path.insert(0, str(PROJECT / "src"))

# ICO 里塞多档尺寸，Windows 在任务栏/桌面/开始菜单各取所需
SIZES = (16, 24, 32, 48, 64, 128, 256)

BG = "#1c1d22"      # 与 Theme 暗色底一致
ACCENT = "#4ea1ff"  # Theme.accent
ACCENT2 = "#7bd88f"  # Theme.green
LINE = "#f4f5f7"


def draw(size: int) -> bytes:
    """画一张 size×size 的图标，返回 PNG 字节。"""
    from PySide6.QtCore import QBuffer, QByteArray, QRectF, Qt  # noqa: PLC0415
    from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen  # noqa: PLC0415

    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    u = size / 256.0  # 以 256 为设计基准等比缩放

    # ---- 圆角底 ----
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(BG)))
    r = 52 * u
    p.drawRoundedRect(QRectF(12 * u, 12 * u, 232 * u, 232 * u), r, r)

    # ---- 5 根声波柱（高度对称，像波形/均衡器）----
    # 归一化高度：低-中-高-中-低
    bars = (0.38, 0.66, 1.0, 0.66, 0.38)
    bw = 24 * u            # 单柱宽
    gap = 16 * u
    total = len(bars) * bw + (len(bars) - 1) * gap
    x0 = (size - total) / 2.0
    cy = size / 2.0
    maxh = 150 * u
    radius = bw / 2.0

    for i, frac in enumerate(bars):
        h = maxh * frac
        x = x0 + i * (bw + gap)
        col = QColor(ACCENT) if i % 2 == 0 else QColor(ACCENT2)
        p.setBrush(QBrush(col))
        p.drawRoundedRect(QRectF(x, cy - h / 2.0, bw, h), radius, radius)

    # ---- 16px 下柱状太糊，改用更粗的 3 根 + 更亮对比 ----
    if size <= 24:
        p.setBrush(QBrush(QColor(ACCENT)))
        p.drawRect(QRectF(x0, cy - maxh * 0.5, bw, maxh))
        p.setBrush(QBrush(QColor(ACCENT2)))
        p.drawRect(QRectF(x0 + bw + gap, cy - maxh * 0.5, bw, maxh))
        p.setBrush(QBrush(QColor(ACCENT)))
        p.drawRect(QRectF(x0 + 2 * (bw + gap), cy - maxh * 0.5, bw, maxh))

    # ---- 右下角放大镜把手（"抓"的语义）；小尺寸省略避免糊成一团 ----
    if size >= 32:
        pen = QPen(QColor(LINE))
        pen.setWidthF(max(3.0, 9 * u))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        cr = 30 * u
        ccx, ccy = 176 * u, 168 * u
        p.drawEllipse(QRectF(ccx - cr / 2, ccy - cr / 2, cr, cr))
        # 把手
        p.drawLine(
            int(ccx + cr * 0.35), int(ccy + cr * 0.35),
            int(ccx + cr * 1.15), int(ccy + cr * 1.15),
        )

    p.end()

    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def write_ico(frames: list[tuple[int, bytes]], path: Path) -> None:
    """把多张 PNG 打成 ICO（Vista+ 支持 PNG 压缩帧）。"""
    n = len(frames)
    header = struct.pack("<HHH", 0, 1, n)   # reserved, type=1(icon), count
    offset = 6 + 16 * n
    entries = b""
    body = b""
    for size, data in frames:
        w = 0 if size >= 256 else size   # 256 在 ICO 里用 0 表示
        h = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII",
            w, h, 0, 0,          # width, height, colors, reserved
            1, 32,               # planes, bitcount
            len(data), offset,   # size, offset
        )
        body += data
        offset += len(data)
    path.write_bytes(header + entries + body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="覆盖已存在的图标")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ico = OUT_DIR / "icon.ico"
    png = OUT_DIR / "icon.png"

    if ico.exists() and not args.force:
        print("已存在（--force 覆盖）：", ico)
        return 0

    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    QApplication(sys.argv)  # QImage/QPainter 需要 QGuiApplication 实例

    frames = [(s, draw(s)) for s in SIZES]
    write_ico(frames, ico)
    # 单独再存一张 256 PNG（LNK / 关于对话框 / 网页预览都可能用）
    png.write_bytes(dict(frames)[256])

    print("生成：", ico, ico.stat().st_size, "B")
    print("生成：", png, png.stat().st_size, "B")
    print("尺寸：", ", ".join(str(s) for s in SIZES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
