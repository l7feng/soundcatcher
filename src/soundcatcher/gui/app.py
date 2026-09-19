"""SoundCatcher 图形界面入口（阶段 2）。

启动流程：QApplication → 单例锁（防双开同一数据目录）→ 注册 AppBackend
到 QML 上下文 → 加载 ``main.qml``。数据目录可用 ``SOUNDCATCHER_DATA_HOME``
覆盖（默认 ``Config.data_dir``）。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication, QMessageBox

from ..config import Config
from .backend import _data_home, AppBackend
from .fonts import apply_ui_font, register_bundled_fonts

logger = logging.getLogger(__name__)

QML_FILE = Path(__file__).resolve().parent / "main.qml"


def main(argv: list[str] | None = None) -> int:
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("SoundCatcher")
    app.setApplicationDisplayName("SoundCatcher")

    # 界面字体：显式选一个含 CJK 字形的族，否则 offscreen/精简环境中文会渲染成方框
    register_bundled_fonts()
    family = apply_ui_font(app)
    logger.debug("界面字体：%s", family)

    data_home = _data_home()

    # 单例锁：同一数据目录只允许一个 GUI。GUI 只读，与扫描进程不冲突；
    # 此锁仅防"两个 GUI 同时打开同一库"。写在数据目录，随库清理。
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

    engine = QQmlApplicationEngine()
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