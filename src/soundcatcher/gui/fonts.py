"""字体装配：为 GUI 选定一个含 CJK 字形的界面字体。

Windows 自带字体里按优先级挑第一个存在的（微软雅黑 → 等线 → 黑体 → 宋体 → Noto Sans SC）。
Linux/macOS 上走 Qt 的默认族名列表。

背景：QML 侧未声明 ``font.family`` 时，Qt 走平台默认族；在 offscreen 平台该族
**不含 CJK 字形**，中文会整片渲染成方框（豆腐块）。显式指定族名即可修复，
同时也让暗色主题下的中英文混排字重一致。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

# 候选族名：按「现代无衬线 + 中文覆盖好」排序
_WIN_CANDIDATES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "DengXian",
    "SimHei",
    "Noto Sans SC",
    "SimSun",
)

_UNIX_CANDIDATES = (
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "WenQuanYi Micro Hei",
    "PingFang SC",
    "Microsoft YaHei",
)

# 候选字体**文件**：族名不可用时直接注册文件（offscreen 平台 families() 恒为空）
_WIN_FONT_FILES = (
    r"C:\Windows\Fonts\msyh.ttc",       # 微软雅黑
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\Deng.ttf",       # 等线
    r"C:\Windows\Fonts\simhei.ttf",     # 黑体
    r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
    r"C:\Windows\Fonts\simsun.ttc",     # 宋体
)

_UNIX_FONT_FILES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)


def _font_files() -> tuple[str, ...]:
    return _WIN_FONT_FILES if sys.platform == "win32" else _UNIX_FONT_FILES


def register_bundled_fonts() -> list[str]:
    """把工程内 ``assets/fonts/*``（若存在）注册进字体库，返回已注册族名。

    为将来「打包内置字体」留口：现在没有该目录就静默跳过。
    """
    fonts_dir = Path(__file__).resolve().parent / "assets" / "fonts"
    return _register_dir(fonts_dir)


def _register_dir(fonts_dir: Path) -> list[str]:
    if not fonts_dir.is_dir():
        return []
    added: list[str] = []
    for path in sorted(fonts_dir.glob("*")):
        if path.suffix.lower() not in {".ttf", ".ttc", ".otf"}:
            continue
        fid = QFontDatabase.addApplicationFont(str(path))
        if fid >= 0:
            added.extend(QFontDatabase.applicationFontFamilies(fid))
    return added


def register_system_cjk_font() -> list[str]:
    """直接**按文件路径**注册系统中文字体，返回注册成功的族名。

    必需原因：``QT_QPA_PLATFORM=offscreen`` 下 ``QFontDatabase.families()`` 返回空表
    （offscreen 后端不加载系统字体库），只能靠 ``addApplicationFont`` 显式注入文件。
    """
    added: list[str] = []
    for path in _font_files():
        if not os.path.exists(path):
            continue
        fid = QFontDatabase.addApplicationFont(path)
        if fid >= 0:
            added.extend(QFontDatabase.applicationFontFamilies(fid))
        if added:
            break  # 第一个成功注册的即可，避免同族多权重干扰
    return added


def pick_ui_font_family() -> str | None:
    """返回当前可用的候选族名；都没有则返回 None（用 Qt 默认）。"""
    available = set(QFontDatabase.families())
    candidates = _WIN_CANDIDATES if sys.platform == "win32" else _UNIX_CANDIDATES
    for family in candidates:
        if family in available:
            return family
    # 退化：模糊匹配任意含 CJK 关键词的族
    for family in sorted(available):
        low = family.lower()
        if any(k in low for k in ("yahei", "hei", "song", "kai", "cjk", "noto sans sc")):
            return family
    return None


def resolve_ui_font() -> tuple[str | None, str]:
    """定出界面字体族。返回 ``(族名或 None, 来源说明)``。

    顺序：① 已可用族名 → ② 注册系统字体文件后再查 → ③ 工程内置字体 → ④ 放弃。
    """
    family = pick_ui_font_family()
    if family:
        return family, "系统字体库"

    added = register_system_cjk_font()
    if added:
        family = pick_ui_font_family() or added[0]
        return family, "注册字体文件"

    bundled = register_bundled_fonts()
    if bundled:
        return bundled[0], "工程内置字体"

    return None, "无可用的 CJK 字体"


def apply_ui_font(app) -> str:
    """给 QApplication 设置界面字体，返回实际选用的族名（或 '<default>'）。"""
    family, source = resolve_ui_font()
    if family:
        font = QFont(family, 10)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        app.setFont(font)
        return f"{family} ({source})"
    return "<default>"
