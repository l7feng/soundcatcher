"""对【真实库】做 offscreen 渲染截图 —— 展示 GUI 在 10.8 万条库下的真实界面。

与 ``screenshot_gui.py`` 的区别：那个用 data-test 小库；本脚本用真实 ``data/``。
只读打开（GUI 本身就是只读会话），不写任何数据。

用法::

    python scripts/shot_real_lib.py [输出前缀]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
# 不设 SOUNDCATCHER_DATA_HOME -> 用默认（真实 data/）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(PROJECT / "src"))

from PySide6.QtCore import QTimer, QUrl  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from soundcatcher.gui.app import QML_FILE  # noqa: E402
from soundcatcher.gui.backend import AppBackend  # noqa: E402
from soundcatcher.gui.fonts import apply_ui_font, register_bundled_fonts  # noqa: E402

PREFIX = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT / "data-test" / "real"
STEPS: list[tuple[str, object]] = []


def main() -> int:
    app = QApplication(sys.argv)
    register_bundled_fonts()
    family = apply_ui_font(app)
    print(f"[font] {family}")
    engine = QQmlApplicationEngine()
    backend = AppBackend()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(QML_FILE)))
    roots = engine.rootObjects()
    assert roots, "QML 加载失败"
    win: QQuickWindow = roots[0]
    win.show()

    state = {"shots": 0}

    def snap(tag: str) -> None:
        name = f"{PREFIX.name}-{state['shots']:02d}-{tag}.png"
        out = PREFIX.with_name(name)
        img = win.grabWindow()
        img.save(str(out))
        state["shots"] += 1
        print(f"[snap] {out.name} ({img.width()}x{img.height()})")

    def on_ready(ok: bool, msg: str) -> None:
        print(f"[ready] ok={ok} msg={msg!r}")
        if not ok:
            return
        QTimer.singleShot(600, step1)

    def step1() -> None:
        snap("ready")
        print("--- search: glass breaking (semantic) ---")
        backend.doSearch("glass breaking", "semantic", 30)
        QTimer.singleShot(2500, step2)

    def step2() -> None:
        snap("search-semantic-en")
        print("--- search: 玻璃破碎的声音 (hybrid) ---")
        backend.doSearch("玻璃破碎的声音", "hybrid", 30)
        QTimer.singleShot(4000, step3)

    def step3() -> None:
        snap("search-hybrid-zh")
        print("--- keyword: metal ---")
        backend.doSearch("metal", "keyword", 30)
        QTimer.singleShot(2500, step4)

    def step4() -> None:
        snap("search-keyword")
        print("--- similar: Windows Recycle.wav ---")
        ref = r"C:\Windows\Media\Windows Recycle.wav"
        backend.doSimilar(ref)
        QTimer.singleShot(3000, step5)

    def step5() -> None:
        snap("similar")
        print("--- waveform ---")
        backend.loadWaveform(1, r"C:\Windows\Media\Windows Recycle.wav")
        QTimer.singleShot(2000, step6)

    def step6() -> None:
        snap("waveform")
        print("--- done ---")
        backend.shutdown()
        app.quit()

    backend.ready.connect(on_ready)
    QTimer.singleShot(60000, lambda: (print("[timeout]"), backend.shutdown(), app.quit()))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
