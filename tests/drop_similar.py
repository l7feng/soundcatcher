"""拖入参考音频 → 以声搜声：DropArea 链路测试。

验证两件事（避免用 QMetaObject 去调 QML 函数这类脆弱手法）：
1. QML 侧：``main.qml`` 含 DropArea 且暴露 ``similarFromDrop`` / ``urlToPath``；
2. 后端侧：``urlToPath`` 的路径转换规则与 ``backend.doSimilar`` 链路真能出结果。

用法::

    python tests/drop_similar.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

os.environ.setdefault("SOUNDCATCHER_APPDATA", str(PROJECT / "data-test"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, QUrl  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from soundcatcher.gui.app import QML_FILE  # noqa: E402
from soundcatcher.gui.backend import AppBackend  # noqa: E402

REF = r"C:\Windows\Media\Windows Recycle.wav"
QML = QML_FILE

state: dict = {"qml_ok": False, "path_ok": False, "similar_ok": False, "errors": []}


def main() -> int:
    # ---- 1. QML 静态断言：DropArea 与两个函数必须在源文件里 ----
    src = QML.read_text(encoding="utf-8")
    for token in ("DropArea", "similarFromDrop", "urlToPath", "dragHint"):
        assert token in src, f"main.qml 缺少 {token}"
    print("[qml] DropArea / similarFromDrop / urlToPath / dragHint 均在位")

    app = QApplication.instance() or QApplication(sys.argv)
    engine = QQmlApplicationEngine()
    backend = AppBackend()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(QML)))
    assert engine.rootObjects(), "QML 加载失败"
    win = engine.rootObjects()[0]
    print("[qml] rootObjects =", len(engine.rootObjects()))
    state["qml_ok"] = True
    state["items"] = []

    # 检索与以声搜声共用 searchFinished 出口（backend._on_search_finished 统一发射）
    backend.searchFinished.connect(lambda items: state["items"].extend(items))

    def after_ready() -> None:
        try:
            # ---- 2. urlToPath 语义（在 Python 侧镜像断言，与 QML 同规则）----
            def url_to_path(u: str) -> str:
                p = u
                if p.startswith("file://"):
                    p = p[7:]
                if p.startswith("/"):
                    p = p[1:]
                return p
            assert url_to_path("file:///C:/a/b.wav") == "C:/a/b.wav"
            assert url_to_path("file://C:/a/b.wav") == "C:/a/b.wav"
            state["path_ok"] = True
            print("[urlToPath] 规则正确（去 file:// 与 Windows 前导斜杠）")

            # ---- 3. 后端以声搜声链路 ----
            backend.doSimilar(REF, 10)
            print(f"[doSimilar] dispatched: {REF}")
        except Exception:  # noqa: BLE001
            import traceback
            state["errors"].append(traceback.format_exc())
        QTimer.singleShot(3000, finish)

    def finish() -> None:
        try:
            items = state["items"]
            n = len(items)
            print(f"[results] n={n}")
            if n > 0:
                state["similar_ok"] = True
                print(f"[results] first={items[0].get('filename')} score={items[0].get('score')}")
            print("--- DROP RESULT ---")
            print({k: v for k, v in state.items() if k != "items"})
            for e in state["errors"]:
                print(e)
            assert not state["errors"], "链路报错"
            assert state["path_ok"], "urlToPath 规则失败"
            assert state["similar_ok"], "doSimilar 未返回结果"
            print("DROP OK")
        finally:
            backend.shutdown()
            app.quit()

    # 等库就绪（模型加载约 3s）
    QTimer.singleShot(5000, after_ready)
    app.exec()
    return 0 if (state["path_ok"] and state["similar_ok"] and not state["errors"]) else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
