"""启动 SoundCatcher GUI，并由 **Qt 自己**截图（绕过 GDI 抓不到 GPU 内容的问题）。

为什么需要它：
    Qt Quick 用 GPU（OpenGL / D3D）渲染，`PrintWindow` / BitBlt 等 GDI 手段
    只能拿到黑图或白图（实测：2560x1369 全黑、1380x880 全白）。
    `QQuickWindow.grabWindow()` 在进程内读取渲染结果，是唯一可靠的方式。

为什么不能单独跑截图进程：
    `grabWindow()` 必须读**本进程**的渲染表面，跨进程无法访问。

做法：
    复制 `app.main()` 的启动逻辑，但在 `app.exec()` 之前挂一个 QTimer，
    延时后遍历可见 QQuickWindow 逐个 `grabWindow()` 存 PNG。

用法：
    python scripts/run_gui_with_shot.py [输出目录] [首次等待秒数]
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

out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT / "data-test" / "live"
first_wait = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
out_dir.mkdir(parents=True, exist_ok=True)


def grab(tag: str) -> None:
    wins = [w for w in QApplication.allWindows() if w.isVisible() and isinstance(w, QQuickWindow)]
    if not wins:
        print(f"[shot:{tag}] 没有可见的 QQuickWindow", flush=True)
        return
    win = max(wins, key=lambda w: w.width() * w.height())
    path = out_dir / f"live-{tag}-{time.strftime('%H%M%S')}.png"
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

    # 截完图就退出，避免留一个孤儿进程
    def shot_and_quit():
        grab("ready")
        backend.doSearch("glass breaking", "semantic", 30)
        QTimer.singleShot(2500, lambda: (grab("semantic-en"), QTimer.singleShot(1200, _quit)))

    def _quit():
        app.quit()

    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(QML_FILE)))
    if not engine.rootObjects():
        lock.unlock()
        return 1

    QTimer.singleShot(int(first_wait * 1000), shot_and_quit)

    app.aboutToQuit.connect(backend.shutdown)
    rc = app.exec()
    lock.unlock()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
