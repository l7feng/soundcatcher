"""只加载 main.qml 并把 QML 引擎的告警/错误原样打出来（排查加载失败用）。

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
from PySide6.QtWidgets import QApplication  # noqa: E402

_msgs: list[str] = []


def _handler(t, _ctx, m):
    if t in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        _msgs.append(m)


def main() -> int:
    qInstallMessageHandler(_handler)
    app = QApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(PROJECT / "src" / "soundcatcher" / "gui"))

    qml = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT / "src" / "soundcatcher" / "gui" / "main.qml"
    engine.load(QUrl.fromLocalFile(str(qml)))
    print("ROOTS:", len(engine.rootObjects()))

    seen: set[str] = set()
    for m in _msgs:
        if m in seen:
            continue
        seen.add(m)
        if any(k in m for k in ("Error", ".qml", "Cannot", "Invalid", "Unable", "not exist")):
            print(">>", m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
