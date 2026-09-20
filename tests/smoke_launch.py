"""整链路启动冒烟：真的跑一遍 ``app.main()``（含 settings 引导 + 单例锁 + QML 加载），
6 秒后自动退出，避免留后台进程。

比 smoke_gui.py 更「真」的地方：走的是生产入口 ``main()``，因此能验证
① settings.json 引导 → ② 环境变量注入 → ③ QLockFile 单例锁 → ④ QML 加载 全链路。

用法::

    python tests/smoke_launch.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def main() -> int:
    from soundcatcher.gui import app as gapp

    orig_exec = QApplication.exec
    # PySide6 里 QApplication.exec 是**静态/无参**签名（实例调用不传 self），
    # 所以包装函数必须显式收 self 再走原始 bound 方法
    raw_exec = QApplication.exec_

    def patched(self=None):  # noqa: ANN001
        inst = self if isinstance(self, QApplication) else QApplication.instance()
        QTimer.singleShot(6000, inst.quit)
        return raw_exec(inst)

    QApplication.exec = patched  # type: ignore[method-assign]
    QApplication.exec_ = patched  # type: ignore[method-assign]

    rc = gapp.main([])
    print("app.main() returned:", rc)
    print("RESULT:", "LAUNCH OK" if rc == 0 else f"FAILED rc={rc}")
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
