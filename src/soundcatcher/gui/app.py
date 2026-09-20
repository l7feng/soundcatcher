"""SoundCatcher 图形界面入口（阶段 2）。

启动流程：**载入 settings.json 并注入环境变量** → QApplication → 单例锁
（防双开同一数据目录）→ 注册 AppBackend 到 QML 上下文 → 加载 ``main.qml``。

**为什么必须先载入 settings**：可改路径是通过写 ``SOUNDCATCHER_*`` 环境变量生效的，
而 ``Config`` / ``AppBackend`` 在构造时就会读它们。顺序错了路径设置就不生效。

数据目录可用 ``SOUNDCATCHER_DATA_HOME`` 覆盖；环境变量优先级高于
``settings.json``（保证测试/便携场景可强制覆盖）。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication, QMessageBox

from .fonts import apply_ui_font, register_bundled_fonts
from .settings import Settings, settings_path

logger = logging.getLogger(__name__)

GUI_DIR = Path(__file__).resolve().parent
QML_FILE = GUI_DIR / "main.qml"


def _bootstrap_settings() -> Settings:
    """载入 settings.json 并把路径偏好注入环境变量（**必须早于 Config/backend**）。"""
    st = Settings(settings_path())
    st.apply_to_environ()
    return st


def main(argv: list[str] | None = None) -> int:
    # ① 偏好先落地：路径偏好靠环境变量生效，晚于 backend 构造就白设了
    _bootstrap_settings()

    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("SoundCatcher")
    app.setApplicationDisplayName("SoundCatcher")

    # ② 界面字体：显式选一个含 CJK 字形的族，否则 offscreen/精简环境中文会渲染成方框
    register_bundled_fonts()
    family = apply_ui_font(app)
    logger.debug("界面字体：%s", family)

    engine = QQmlApplicationEngine()
    # ③ QML 单例（Theme / I18n）依赖同目录 qmldir；显式加导入路径，
    #    避免打包（Nuitka/资源内嵌）后路径推断失败
    engine.addImportPath(str(GUI_DIR))

    # 数据目录在 settings 注入之后才解析
    from .backend import _data_home, AppBackend  # noqa: PLC0415 (须在 env 注入后构造)

    data_home = _data_home()

    # ④ 单例锁：同一数据目录只允许一个 GUI。GUI 只读，与扫描进程不冲突；
    #    此锁仅防"两个 GUI 同时打开同一库"。写在数据目录，随库清理。
    data_home.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(data_home / "gui.lock"))
    lock.setStaleLockTime(60_000)
    if not lock.tryLock(150):
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("SoundCatcher")
        box.setText("SoundCatcher 已在运行（同一数据目录）。\n请检查系统托盘或任务管理器。")
        box.exec()
        return 1

    backend = AppBackend()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(QML_FILE)))
    if not engine.rootObjects():
        lock.unlock()
        return 1

    app.aboutToQuit.connect(backend.shutdown)
    rc = app.exec()
    lock.unlock()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
