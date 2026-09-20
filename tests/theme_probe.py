"""验证主题×语言热切换 + 侧栏可拖拽几何。

**重要**：QML 里用 `function applyTheme(mode)` 声明的函数，从 Python 侧
`invokeMethod` 调用不可靠（参数是 QML 变体，元对象系统里没有匹配的 slot 签名）。
所以本探针**不直接调那两个 QML 函数**，而是复刻菜单项的调用路径：
`backend.setTheme/setLanguage`（持久化）+ `Theme.setMode/I18n.setLang`（热生效）。
两条路都验证到，就等于验证了菜单点下去会发生什么。

用法::

    python tests/theme_probe.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from PySide6.QtCore import QObject, QTimer, QUrl  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from soundcatcher.gui.app import QML_FILE  # noqa: E402
from soundcatcher.gui.backend import AppBackend  # noqa: E402

fails: list[str] = []


def chk(cond: bool, msg: str) -> None:
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def main() -> int:
    app = QApplication(sys.argv)
    engine = QQmlApplicationEngine()
    backend = AppBackend()
    engine.rootContext().setContextProperty("backend", backend)
    engine.addImportPath(str(PROJECT / "src" / "soundcatcher" / "gui"))
    engine.load(QUrl.fromLocalFile(str(QML_FILE)))
    if not engine.rootObjects():
        print("LOAD FAILED")
        return 1
    win = engine.rootObjects()[0]

    # QML 单例：本地 qmldir 单例没有独立 uri，singletonInstance 拿不到 —— 这是
    # 探针的限制，不是产品问题。改为**经 QML 属性间接驱动**（见下方 heat()）。
    theme_obj = None
    for uri in ("", "SoundCatcherGui", "gui"):
        try:
            theme_obj = engine.singletonInstance(uri, "Theme")
            break
        except Exception:  # noqa: BLE001
            continue
    print("Theme 单例：", "OK" if theme_obj is not None else "拿不到（改为经由 root 属性验证热切换）")

    def find(oid: str) -> QObject | None:
        return win.findChild(QObject, oid)

    def probe(mode: str, lang: str) -> dict:
        """经 QML 的无参 probeApply() 驱动切换，再读回 probeResult。"""
        win.setProperty("probeArgs", [mode, lang])
        QApplication.processEvents()
        ok = win.metaObject().invokeMethod(win, "probeApply")
        QApplication.processEvents()
        if not ok:
            return {"_invokeFailed": True}
        # probeResult 是 QJSValue，不是 dict → 用 toVariant() 转成 Python 对象
        v = win.property("probeResult")
        if hasattr(v, "toVariant"):
            v = v.toVariant()
        return dict(v) if v else {}

    def run() -> None:
        # ---------- [1] 初始态 ----------
        print("\n[1] 初始态")
        cbg0 = win.property("cBg")
        print("   title =", win.property("title"))
        print("   cBg   =", cbg0)
        chk(cbg0 is not None, "cBg 已绑定（Theme 接入生效）")
        # QColor 归一成 #rrggbb 字符串，后面才能与 probeResult 的字符串直接比
        cbg0_hex = "#%02x%02x%02x" % (cbg0.red(), cbg0.green(), cbg0.blue())
        print("   cBg hex =", cbg0_hex)

        # ---------- [2] 暗 → 亮（走菜单同款路径） ----------
        print("\n[2] 切亮色")
        r_light = probe("light", "zh")
        print("   ", r_light)
        chk(not r_light.get("_invokeFailed"), "probeApply() 可调用（无参函数）")
        chk(str(r_light.get("bg")).lower() != cbg0_hex.lower(),
            f"亮色后 bg 变化：{cbg0_hex} → {r_light.get('bg')}")
        chk(r_light.get("isDark") is False, "亮色态 isDark=False")

        # ---------- [3] 亮 → 暗 ----------
        print("\n[3] 切回暗色")
        r_dark = probe("dark", "zh")
        print("   ", r_dark)
        chk(r_dark.get("isDark") is True, "暗色态 isDark=True")
        chk(str(r_dark.get("bg")).lower() == cbg0_hex.lower(),
            f"切回暗色后 bg 复原：{r_dark.get('bg')} vs {cbg0_hex}")

        # ---------- [4] 随系统 ----------
        print("\n[4] 切随系统")
        r_sys = probe("system", "zh")
        print("   ", r_sys)
        chk(r_sys.get("themeMode") == "system", "mode=system 生效")

        # ---------- [5] 语言 ----------
        print("\n[5] 切英文")
        r_en = probe("dark", "en")
        print("   title =", r_en.get("title"))
        chk("Local AI Sound Library" in str(r_en.get("title")), "标题切为英文")
        chk(r_en.get("lang") == "en", "I18n.lang=en")
        print("\n[6] 切回中文")
        r_zh = probe("dark", "zh")
        chk("本地 AI 音效库" in str(r_zh.get("title")), "标题切回中文")

        # ---------- [7] 侧栏几何（SplitView + 持久化） ----------
        print("\n[7] 侧栏几何")
        sb = find("sidebar")
        chk(sb is not None, "找到 sidebar（objectName 已设）")
        if sb is not None:
            print("   sidebar.width =", r_zh.get("sidebarWidth"))
            chk(abs(r_zh.get("sidebarWidth", 0) - 320) < 2,
                f"侧栏宽度 = 320（实测 {r_zh.get('sidebarWidth')}）")
        ucs = find("ucsTreeView")
        chk(ucs is not None, "找到 ucsTreeView")
        if ucs is not None:
            h = r_zh.get("treeHeight")
            print("   ucsTreeView.height =", h)
            chk(h is not None and h > 200, f"树视口高度 > 200px（修复前仅 105；实测 {h}）")

        # ---------- [8] 侧栏宽度持久化 ----------
        print("\n[8] 侧栏宽度持久化")
        backend.setSidebarWidth(400)
        chk(backend.getSidebarWidth() == 400, "setSidebarWidth(400) 生效")
        backend.setSidebarWidth(320)
        chk(backend.getSidebarWidth() == 320, "复位回 320")

        # ---------- [9] 路径设置 ----------
        print("\n[9] pathInfo()")
        try:
            info = backend.pathInfo()
            chk(isinstance(info, list) and len(info) == 5, f"pathInfo() 返回 5 条（实测 {len(info) if isinstance(info, list) else type(info)}）")
            for it in info:
                print(f"   - {it.get('key'):10s} custom={it.get('custom')} envForced={it.get('envForced')}  {it.get('path')}")
            keys = {it.get("key") for it in info}
            chk(keys == {"dataHome", "stateDir", "modelsDir", "catalogDir", "exportDir"},
                f"5 个可改路径齐备：{sorted(keys)}")
        except Exception as e:  # noqa: BLE001
            chk(False, f"pathInfo() 异常：{e}")

        # ---------- [10] 主题 token ----------
        print("\n[10] 主题色收敛")
        chk(str(r_zh.get("onColor")) != "", "onColor token 可取")

        # ---------- [11] 对话框存在 ----------
        print("\n[11] 新增对话框")
        for oid, name in (("pathsDialog", "路径设置"), ):
            d = find(oid)
            chk(d is not None, f"{name}对话框已定义（objectName={oid}）")

        # ---------- [12] 路径迁移预演 ----------
        print("\n[12] previewPathMove / setPath")
        import tempfile, pathlib as _pl
        tmp = _pl.Path(tempfile.mkdtemp(prefix="sc-mig-"))
        src = tmp / "old"; src.mkdir(); (src / "a.txt").write_text("x")
        dst = tmp / "new"
        r = backend.previewPathMove("exportDir", str(dst))
        print("   preview:", r.get("msg"))
        chk(r.get("ok") is True, "previewPathMove 返回 ok")

        # 拒绝套娃（新路径在旧路径内）
        nested = dst / "inner"
        r2 = backend.previewPathMove("exportDir", str(nested))
        print("   nested preview ok =", r2.get("ok"))
        # 注意：exportDir 的旧路径是 Downloads，与新 tmp 无包含关系 → 这里应 ok
        # 真实套娃拒绝由 settings.migrate_path 单测覆盖（见 tests/test_settings_migrate.py）

        # env-forced 拒绝
        os.environ["SOUNDCATCHER_CATALOG"] = "C:/forced"
        r3 = backend.setPath("catalogDir", str(tmp / "cat"))
        print("   envForced setPath ok =", r3.get("ok"), "|", r3.get("msg")[:40])
        chk(r3.get("ok") is False, "环境变量强制时 setPath 被拒绝")
        del os.environ["SOUNDCATCHER_CATALOG"]

        # 未知 key 拒绝
        r4 = backend.setPath("nopeKey", "C:/x")
        chk(r4.get("ok") is False, "未知 key 被拒绝")

        # ---------- [13] appVersion ----------
        print("\n[13] appVersion()")
        v = backend.appVersion()
        print("   version =", v)
        chk(isinstance(v, str) and len(v) > 0, "appVersion() 返回非空字符串")

        app.quit()

        app.quit()

    QTimer.singleShot(2000, run)
    app.exec()

    print("\n=== RESULT ===")
    if fails:
        for f in fails:
            print("  FAIL:", f)
        return 1
    print("  THEME PROBE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
