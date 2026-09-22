"""验证主题×语言热切换 + 侧栏可拖拽几何 + 路径设置。

**两条重要工程约束**（踩过的坑，勿回退）：

1. QML 里用 `function applyTheme(mode)` 声明的**带参函数**，从 Python 侧
   `invokeMethod` 不可靠（参数是 QML 变体，元对象系统里没有匹配的 slot 签名，
   实测返回 False）。所以探针**不直接调带参 QML 函数**，而是复刻菜单项的
   调用路径：`backend.setTheme/setLanguage`（持久化）+ QML 无参桥
   `probeApply()`（读 `probeArgs` 属性 → 热生效 → 回填 `probeResult`）。

2. **进程退出码不可信**：本机在 WorkBuddy 沙箱里跑 Qt 脚本，`python` 进程
   正常跑完（日志显示 `exec returned`）但 shell 报 `RC=127`（`command not
   found` 假象，源于 shell 包装脚本身的问题）。**因此判定结果只看落盘的日志
   内容，不看返回码。** 脚本会把全部输出写入 `tests/_theme_probe.log`，
   同时在 stdout 打一份（stdout 被吞时看日志文件即可）。

用法::

    python tests/theme_probe.py            # 跑完看 stdout 或 tests/_theme_probe.log
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

LOG_PATH = Path(__file__).resolve().parent / "_theme_probe.log"

fails: list[str] = []
_lines: list[str] = []


def out(msg: str = "") -> None:
    """同时写日志文件与 stdout（stdout 被沙箱吞掉时仍有留痕）。"""
    _lines.append(msg)
    try:
        print(msg, flush=True)
    except Exception:  # noqa: BLE001
        pass


def chk(cond: bool, msg: str) -> None:
    out(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def main() -> int:
    from PySide6.QtCore import QObject, QTimer, QUrl  # noqa: PLC0415
    from PySide6.QtQml import QQmlApplicationEngine  # noqa: PLC0415
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    from soundcatcher.gui.app import QML_FILE  # noqa: PLC0415
    from soundcatcher.gui.backend import AppBackend  # noqa: PLC0415

    app = QApplication(sys.argv)
    engine = QQmlApplicationEngine()
    backend = AppBackend()
    engine.rootContext().setContextProperty("backend", backend)
    engine.addImportPath(str(PROJECT / "src" / "soundcatcher" / "gui"))
    engine.load(QUrl.fromLocalFile(str(QML_FILE)))
    if not engine.rootObjects():
        out("LOAD FAILED")
        return 1
    win = engine.rootObjects()[0]

    # QML 单例：本地 qmldir 单例没有独立 uri，singletonInstance 拿不到 —— 这是
    # 探针的限制，不是产品问题。改为**经 QML 属性间接驱动**（见下方 probe()）。
    theme_obj = None
    for uri in ("", "SoundCatcherGui", "gui"):
        try:
            theme_obj = engine.singletonInstance(uri, "Theme")
            break
        except Exception:  # noqa: BLE001
            continue
    out("Theme 单例：" + ("OK" if theme_obj is not None else "拿不到（改为经由 root 属性验证热切换）"))

    def find(oid: str) -> QObject | None:
        return win.findChild(QObject, oid)

    def pump(ms: int = 60) -> None:
        """跑一小段真实事件循环。

        `processEvents()` 只清队列里**当前已有**的事件；`Qt.callLater` 排的回调
        需要事件循环再转一圈才执行。这里用一个极短的 QEventLoop 确保 callLater /
        布局 / 主题收敛回调都跑完（实测 processEvents 单用会让 probeResult 恒为空）。
        """
        from PySide6.QtCore import QEventLoop, QTimer  # noqa: PLC0415

        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def probe(mode: str, lang: str) -> dict:
        """经 QML 的三段式无参函数驱动切换，再读回 probeResult。

        `probeApply()`（切主题/语言）→ `probeToggle()`（展开 UCS 树 + 切到该页签）
        → `probeSample()`（采样并复原）。三段之间必须各泵一轮事件循环：
        QML 里主题收敛与 StackLayout 重新布局都要等到下一帧，同步连读只会拿到
        旧几何（树高恒为 0）。
        """
        win.setProperty("probeArgs", [mode, lang])
        QApplication.processEvents()
        ok = win.metaObject().invokeMethod(win, "probeApply")
        if not ok:
            return {"_invokeFailed": True}
        pump(40)
        win.metaObject().invokeMethod(win, "probeToggle")
        pump(40)
        win.metaObject().invokeMethod(win, "probeSample")
        pump(40)
        # probeResult 是 QJSValue，不是 dict → 用 toVariant() 转成 Python 对象
        v = win.property("probeResult")
        if hasattr(v, "toVariant"):
            v = v.toVariant()
        return dict(v) if v else {}

    def run() -> None:
        # ---------- [1] 初始态 ----------
        out("\n[1] 初始态")
        cbg0 = win.property("cBg")
        out("   title = " + str(win.property("title")))
        out("   cBg   = " + str(cbg0))
        chk(cbg0 is not None, "cBg 已绑定（Theme 接入生效）")
        # QColor 归一成 #rrggbb 字符串，后面才能与 probeResult 的字符串直接比
        cbg0_hex = "#%02x%02x%02x" % (cbg0.red(), cbg0.green(), cbg0.blue())
        out("   cBg hex = " + cbg0_hex)

        # ---------- [2] 暗 → 亮（走菜单同款路径） ----------
        out("\n[2] 切亮色")
        r_light = probe("light", "zh")
        out("    " + str(r_light))
        chk(not r_light.get("_invokeFailed"), "probeApply() 可调用（无参函数）")
        chk(str(r_light.get("bg")).lower() != cbg0_hex.lower(),
            "亮色后 bg 变化：%s → %s" % (cbg0_hex, r_light.get("bg")))
        chk(r_light.get("isDark") is False, "亮色态 isDark=False")

        # ---------- [3] 亮 → 暗 ----------
        out("\n[3] 切回暗色")
        r_dark = probe("dark", "zh")
        out("    " + str(r_dark))
        chk(r_dark.get("isDark") is True, "暗色态 isDark=True")
        chk(str(r_dark.get("bg")).lower() == cbg0_hex.lower(),
            "切回暗色后 bg 复原：%s vs %s" % (r_dark.get("bg"), cbg0_hex))

        # ---------- [4] 随系统 ----------
        out("\n[4] 切随系统")
        r_sys = probe("system", "zh")
        out("    " + str(r_sys))
        chk(r_sys.get("themeMode") == "system", "mode=system 生效")

        # ---------- [5] 语言 ----------
        out("\n[5] 切英文")
        r_en = probe("dark", "en")
        out("   title = " + str(r_en.get("title")))
        chk("Local AI Sound Library" in str(r_en.get("title")), "标题切为英文")
        chk(r_en.get("lang") == "en", "I18n.lang=en")
        out("\n[6] 切回中文")
        r_zh = probe("dark", "zh")
        chk("本地 AI 音效库" in str(r_zh.get("title")), "标题切回中文")

        # ---------- [7] 侧栏几何（SplitView + 持久化） ----------
        out("\n[7] 侧栏几何")
        sb = find("sidebar")
        chk(sb is not None, "找到 sidebar（objectName 已设）")
        if sb is not None:
            out("   sidebar.width = " + str(r_zh.get("sidebarWidth")))
            chk(abs(r_zh.get("sidebarWidth", 0) - 320) < 2,
                "侧栏宽度 = 320（实测 %s）" % r_zh.get("sidebarWidth"))
        ucs = find("ucsTreeView")
        chk(ucs is not None, "找到 ucsTreeView")
        if ucs is not None:
            h = r_zh.get("treeHeight")
            out("   ucsTreeView.height = " + str(h))
            chk(h is not None and h > 200, "树视口高度 > 200px（修复前仅 105；实测 %s）" % h)

        # ---------- [8] 侧栏宽度持久化 ----------
        out("\n[8] 侧栏宽度持久化")
        backend.setSidebarWidth(400)
        chk(backend.getSidebarWidth() == 400, "setSidebarWidth(400) 生效")
        backend.setSidebarWidth(320)
        chk(backend.getSidebarWidth() == 320, "复位回 320")

        # ---------- [9] 路径设置 ----------
        out("\n[9] pathInfo()")
        try:
            info = backend.pathInfo()
            chk(isinstance(info, list) and len(info) == 5,
                "pathInfo() 返回 5 条（实测 %s）" % (len(info) if isinstance(info, list) else type(info)))
            for it in info:
                out("   - %-10s custom=%s envForced=%s  %s" % (
                    it.get("key"), it.get("custom"), it.get("envForced"), it.get("path")))
            keys = {it.get("key") for it in info}
            chk(keys == {"dataHome", "stateDir", "modelsDir", "catalogDir", "exportDir"},
                "5 个可改路径齐备：%s" % sorted(keys))
        except Exception as e:  # noqa: BLE001
            chk(False, "pathInfo() 异常：%s" % e)

        # ---------- [10] 主题 token ----------
        out("\n[10] 主题色收敛")
        chk(str(r_zh.get("onColor")) != "", "onColor token 可取")

        # ---------- [11] 对话框存在 ----------
        out("\n[11] 新增对话框")
        for oid, name in (("pathsDialog", "路径设置"), ("aboutDialog", "关于"),
                          ("shortcutsDialog", "快捷键")):
            d = find(oid)
            chk(d is not None, "%s对话框已定义（objectName=%s）" % (name, oid))

        # ---------- [12] 路径迁移预演 ----------
        out("\n[12] previewPathMove / setPath")
        r = backend.previewPathMove("exportDir", str(Path.home() / "__sc_probe_new"))
        out("   preview: " + str(r.get("msg")))
        chk(r.get("ok") is True, "previewPathMove 返回 ok")

        # env-forced 拒绝
        os.environ["SOUNDCATCHER_CATALOG"] = "C:/forced"
        r3 = backend.setPath("catalogDir", "C:/__sc_probe_cat")
        out("   envForced setPath ok = %s | %s" % (r3.get("ok"), str(r3.get("msg"))[:40]))
        chk(r3.get("ok") is False, "环境变量强制时 setPath 被拒绝")
        del os.environ["SOUNDCATCHER_CATALOG"]

        # 未知 key 拒绝
        r4 = backend.setPath("nopeKey", "C:/x")
        chk(r4.get("ok") is False, "未知 key 被拒绝")

        # ---------- [13] 改标分类搜索（用户选的第 3 项树修复） ----------
        out("\n[13] 改标弹窗的分类搜索")
        catalog = win.property("catalogList")
        if hasattr(catalog, "toVariant"):
            catalog = catalog.toVariant()
        n_cat = len(catalog) if catalog else 0
        out("   内嵌分类表 catalogList = %d 条" % n_cat)
        # 753 是 UCS v8.2.1 全量子分类数；少于它说明弹窗拿不到分类
        chk(n_cat >= 700, "catalogList 载入足够分类（实测 %d，UCS 全量 753）" % n_cat)

        # 真跑一遍过滤：中/英/CatID 三种输入都应命中
        win.setProperty("probeQuery", "")
        QApplication.processEvents()
        for q, why in (("gun", "英文关键词"), ("枪", "中文关键词"), ("GUN", "CatID 大小写不敏感")):
            win.setProperty("probeQuery", q)
            QApplication.processEvents()
            win.metaObject().invokeMethod(win, "probeFilterCats")
            QApplication.processEvents()
            n = win.property("probeHitCount")
            if hasattr(n, "toVariant"):
                n = n.toVariant()
            out("   查询 %-6s (%s) → 命中 %s 条" % (repr(q), why, n))
            chk(isinstance(n, int) and 0 < n < n_cat,
                "搜索 %s 命中收敛（0 < %s < %d）" % (repr(q), n, n_cat))
        win.setProperty("probeQuery", "")
        win.metaObject().invokeMethod(win, "probeFilterCats")
        QApplication.processEvents()
        n_back = win.property("probeHitCount")
        if hasattr(n_back, "toVariant"):
            n_back = n_back.toVariant()
        chk(n_back == n_cat, "清空搜索后恢复全量（%s == %d）" % (n_back, n_cat))

        # ---------- [14] appVersion ----------
        out("\n[14] appVersion()")
        v = backend.appVersion()
        out("   version = " + str(v))
        chk(isinstance(v, str) and len(v) > 0, "appVersion() 返回非空字符串")

        app.quit()

    QTimer.singleShot(2000, run)
    app.exec()

    out("\n=== RESULT ===")
    if fails:
        for f in fails:
            out("  FAIL: " + f)
        code = 1
    else:
        out("  THEME PROBE OK")
        code = 0
    LOG_PATH.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    try:
        rc = main()
    except BaseException:  # noqa: BLE001
        import traceback  # noqa: PLC0415
        _lines.append(traceback.format_exc())
        LOG_PATH.write_text("\n".join(_lines) + "\n", encoding="utf-8")
        rc = 3
    # 注意：进程退出码在当前沙箱里不可信（跑完也报 127），
    # 判定结果请看 tests/_theme_probe.log 末尾的 RESULT 段。
    sys.exit(rc)
