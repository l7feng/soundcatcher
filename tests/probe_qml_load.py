"""只加载 main.qml 并把 QML 引擎的告警/错误原样打出来（排查加载失败用）。

**必须注入 backend**：``main.qml`` 里的 ``backend`` 是 context property（不是
QML 里声明的 property），不注入的话引擎会刷一屏 `ReferenceError: backend is
not defined`，那是探针自身缺项、不是产品问题，会把真正的报错淹掉。

用法::

    python tests/probe_qml_load.py [path/to/main.qml]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from PySide6.QtCore import QtMsgType, QUrl, qInstallMessageHandler  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_msgs: list[str] = []

LOG_PATH = Path(__file__).resolve().parent / "_qml_load.log"
_lines: list[str] = []


def out(msg: str = "") -> None:
    """同时写日志文件与 stdout。

    本机沙箱里 Qt 脚本的 stdout 会被偶发吞掉（进程正常结束但 shell 什么都收不到，
    还会误报 RC=127）。所以结果一律落盘，判定看 ``tests/_qml_load.log``。
    """
    _lines.append(msg)
    try:
        print(msg, flush=True)
    except Exception:  # noqa: BLE001
        pass

# 与产品无关的噪声，按需加白名单（前缀匹配）
_IGNORE = (
    "QFontDatabase: Cannot find font directory",
    "Note that Qt no longer ships fonts",
)


def _handler(t, _ctx, m):
    if t in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        _msgs.append(m)


def main() -> int:
    qInstallMessageHandler(_handler)
    # 与 app.py 保持一致：非原生样式才允许自定义 background/contentItem
    QQuickStyle.setStyle("Basic")
    app = QApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(PROJECT / "src" / "soundcatcher" / "gui"))

    # 注入 backend：否则 backend.* 全部 ReferenceError（探针噪声，非产品问题）
    from soundcatcher.gui.backend import AppBackend  # noqa: PLC0415

    backend = AppBackend()
    engine.rootContext().setContextProperty("backend", backend)

    qml = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT / "src" / "soundcatcher" / "gui" / "main.qml"
    engine.load(QUrl.fromLocalFile(str(qml)))
    out("LOAD: " + str(qml))
    out("ROOTS: %d" % len(engine.rootObjects()))

    kinds = {"customization": 0, "referenceerror": 0, "connections": 0, "other": 0}
    shown: list[str] = []
    seen: set[str] = set()
    for m in _msgs:
        if any(m.startswith(p) for p in _IGNORE):
            continue
        # 同类告警去掉行号与内存地址后去重，避免刷屏
        key = m
        for marker in ("main.qml:", "0x"):
            if marker in key:
                key = key.split(marker)[0] + marker
        if key in seen:
            continue
        seen.add(key)

        if "does not support customization" in m:
            kinds["customization"] += 1
        elif "ReferenceError" in m:
            kinds["referenceerror"] += 1
        elif "in Connections element" in m:
            kinds["connections"] += 1
        else:
            kinds["other"] += 1
        shown.append(m)

    for m in shown:
        out(">> " + m)

    out("\n=== 分类统计（去重后）===")
    for k, v in kinds.items():
        out("  %-16s %d" % (k, v))

    hard = kinds["referenceerror"] + kinds["connections"] + kinds["other"]
    out("\n=== 判定 ===")
    if not engine.rootObjects():
        out("  LOAD FAILED")
        code = 1
    elif hard == 0 and kinds["customization"] == 0:
        out("  QML LOAD CLEAN（无告警）")
        code = 0
    elif hard == 0:
        out("  QML LOAD OK（仅剩样式定制告警，见上）")
        code = 0
    else:
        out("  QML LOAD HAS ISSUES（referenceerror/connections/other 非 0）")
        code = 2
    LOG_PATH.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    try:
        rc = main()
    except BaseException:  # noqa: BLE001
        import traceback  # noqa: PLC0415

        _lines.append(traceback.format_exc())
        LOG_PATH.write_text("\n".join(_lines) + "\n", encoding="utf-8")
        rc = 3
    # 退出码在本机沙箱不可信，看 tests/_qml_load.log 末尾判定
    sys.exit(rc)
