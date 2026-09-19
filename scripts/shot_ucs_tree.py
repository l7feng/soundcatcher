"""验证 GUI UCS 分类树显示真实计数（全量打标后的实数据）。

复用 run_gui_with_shot.py 的结构：进程内 QQuickWindow.grabWindow()。
只做一件事：库就绪 → 等 UCS 树加载 → 截图（UCS 页是默认第一页签）。

用法：
    python scripts/shot_ucs_tree.py [输出目录] [首次等待秒数]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import QLockFile, QTimer, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow  # 必须导入，否则 root 退化为 QWindow
from PySide6.QtWidgets import QApplication, QMessageBox

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from soundcatcher.gui.backend import _data_home, AppBackend  # noqa: E402
from soundcatcher.gui.fonts import apply_ui_font, register_bundled_fonts  # noqa: E402

QML_FILE = PROJECT / "src" / "soundcatcher" / "gui" / "main.qml"

out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT / "data-test" / "ucs-verify"
first_wait = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
out_dir.mkdir(parents=True, exist_ok=True)


def grab(tag: str) -> None:
    wins = [w for w in QApplication.allWindows() if w.isVisible() and isinstance(w, QQuickWindow)]
    if not wins:
        print(f"[shot:{tag}] 没有可见的 QQuickWindow", flush=True)
        return
    win = max(wins, key=lambda w: w.width() * w.height())
    path = out_dir / f"ucs-{tag}-{time.strftime('%H%M%S')}.png"
    pix = win.grabWindow()
    ok = pix.save(str(path))
    print(f"[shot:{tag}] {'OK' if ok else 'FAIL'} {path} ({pix.width()}x{pix.height()})", flush=True)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("SoundCatcher")
    app.setApplicationDisplayName("SoundCatcher")

    register_bundled_fonts()
    print(f"[font] {apply_ui_font(app)}", flush=True)

    data_home = _data_home()
    data_home.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(data_home / "gui.lock"))
    lock.setStaleLockTime(60_000)
    if not lock.tryLock(150):
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("SoundCatcher")
        box.setText("SoundCatcher 已在运行（同一数据目录）。")
        box.exec()
        return 1

    engine = QQmlApplicationEngine()
    backend = AppBackend()

    # 等库就绪 + UCS 树加载后，多截两张（树加载前后各一张，看计数是否出现）
    def shot_ready():
        grab("tree-ready")
        QTimer.singleShot(
            3000, lambda: (grab("tree-loaded"), QTimer.singleShot(800, app.quit))
        )

    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(QML_FILE)))
    if not engine.rootObjects():
        lock.unlock()
        return 1

    QTimer.singleShot(int(first_wait * 1000), shot_ready)

    app.aboutToQuit.connect(backend.shutdown)
    rc = app.exec()
    lock.unlock()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())