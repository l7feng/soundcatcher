"""渲染截图：offscreen 打开 GUI，执行一次搜索后把窗口渲染结果存为 PNG。

用于视觉走查界面布局（开发者无法在这里直接看窗口）。只读，用 data-test。

用法::

    python scripts/screenshot_gui.py [输出.png]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
os.environ["SOUNDCATCHER_DATA_HOME"] = str(PROJECT / "data-test")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(PROJECT / "src"))

from PySide6.QtCore import QTimer, QUrl, QSize  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402  （须先导入，否则实例退化为 QWindow 包装）
from PySide6.QtWidgets import QApplication  # noqa: E402

from soundcatcher.gui.app import QML_FILE  # noqa: E402
from soundcatcher.gui.backend import AppBackend  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT / "data-test" / "gui-preview.png"


def main() -> int:
    app = QApplication(sys.argv)
    engine = QQmlApplicationEngine()
    backend = AppBackend()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(QML_FILE)))
    roots = engine.rootObjects()
    assert roots, "QML 加载失败"
    win: QQuickWindow = roots[0]  # ApplicationWindow
    win.show()

    state = {"n": 0}

    backend.searchFinished.connect(lambda items: state.__setitem__("n", len(items)) or print(f"[results] {len(items)}"))
    backend.ready.connect(lambda ok, msg: print(f"[ready] ok={ok}") or (ok and QTimer.singleShot(1000, do_search)))

    def do_search() -> None:
        print("--- search: 玻璃破碎 ---")
        backend.doSearch("玻璃破碎的声音", "hybrid", 30)

    def snap() -> None:
        img = win.grabWindow()
        img.save(str(OUT))
        print(f"[snap] saved {OUT} ({img.width()}x{img.height()})")
        backend.loadWaveform(1, r"C:\Windows\Media\Windows Recycle.wav")
        QTimer.singleShot(1500, snap2)

    def snap2() -> None:
        img = win.grabWindow()
        out2 = OUT.with_name(OUT.stem + "-wave.png")
        img.save(str(out2))
        print(f"[snap] saved {out2} ({img.width()}x{img.height()})")
        backend.shutdown()
        app.quit()

    QTimer.singleShot(45000, snap)  # 等搜索与首次渲染稳定
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())