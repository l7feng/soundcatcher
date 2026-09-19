"""GUI 冒烟测试：offscreen 启动 → 等库就绪 → 语义搜索 → 波形生成 → 退出。

只读操作，使用独立 ``data-test/`` 目录，绝不碰真实库。

用法::

    python tests/smoke_gui.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
# 冒烟在 **克隆** 的 data-test 上跑：写库（改标 import）不留痕、不碰真实数据
_clone = Path(tempfile.mkdtemp(prefix="sc-smoke-")) / "datatest"
shutil.copytree(PROJECT / "data-test", _clone, dirs_exist_ok=True)
os.environ["SOUNDCATCHER_DATA_HOME"] = str(_clone)
# 收藏/保存搜索：每次用全新临时目录，避免上次运行的持久化数据影响断言
os.environ["SOUNDCATCHER_APPDATA"] = tempfile.mkdtemp(prefix="sc-appdata-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(PROJECT / "src"))

from PySide6.QtCore import QTimer, QUrl  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from soundcatcher import db  # noqa: E402
from soundcatcher.gui.app import QML_FILE  # noqa: E402
from soundcatcher.gui.backend import AppBackend, UcsTreeModel  # noqa: E402

state = {"ready": False, "results": None, "failed": None, "wave": None, "browse": None,
         "fav_ok": False, "saved_ok": False, "scan_ok": False, "export_ok": False,
         "relabel_ok": False, "import_ok": False}


def main() -> int:
    app = QApplication(sys.argv)
    engine = QQmlApplicationEngine()
    backend = AppBackend()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(QML_FILE)))
    assert engine.rootObjects(), "QML 加载失败：rootObjects 为空（看 stderr 的 QML 报错）"

    def on_ready(ok: bool, msg: str) -> None:
        state["ready"] = ok
        print(f"[ready] ok={ok} {msg}")

    def on_results(items: list) -> None:
        state["results"] = items
        print(f"[results] n={len(items)}")
        for it in items[:3]:
            print("   ", it["filename"], f"{it['score']:.3f}", it["source"], it["durationStr"])

    def on_failed(msg: str) -> None:
        state["failed"] = msg
        print(f"[failed] {msg}")

    def on_wave(file_id: int, peaks: list) -> None:
        state["wave"] = len(peaks)
        print(f"[wave] file={file_id} bins={len(peaks)}")

    def on_stats(total: int, embedded: int, failed: int) -> None:
        print(f"[stats] total={total} embedded={embedded} failed={failed}")

    def on_browse(items: list) -> None:
        state["browse"] = len(items)
        print(f"[browse] n={len(items)}")

    backend.ready.connect(on_ready)
    backend.searchFinished.connect(on_results)
    backend.searchFailed.connect(on_failed)
    backend.waveformReady.connect(on_wave)
    backend.statsChanged.connect(on_stats)
    backend.browseFinished.connect(on_browse)

    def run() -> None:
        print("--- model thread ready, run searches ---")
        backend.doSearch("glass breaking", "semantic", 10)
        backend.doSearch("bird", "hybrid", 8)
        path = r"C:\Windows\Media\Windows Recycle.wav"
        backend.playFile(path, "Windows Recycle.wav")
        backend.loadWaveform(1, path)

        # UCS 浏览树：结构 + 计数 + 点叶子浏览
        m = backend.ucsModel
        n_root = m.rowCount()
        print(f"--- UCS tree: roots={n_root} ---")
        assert n_root > 0, "UCS 树为空（data-test/ucs/catalog.json 缺失）"
        first = m.index(0, 0)
        print("first root children:", m.rowCount(first))
        print("first root title:", m.data(first, UcsTreeModel.TitleRole))
        assert m.rowCount(first) > 0, "首个分类没有任何子类"
        leaf = m.index(0, 0, first)
        catid = m.data(leaf, UcsTreeModel.CatIdRole)
        print("first leaf:", m.data(leaf, UcsTreeModel.TitleRole), "| count:", m.data(leaf, UcsTreeModel.CountRole), "| catid:", catid)
        assert m.data(leaf, UcsTreeModel.LeafRole) is True and bool(catid)
        backend.browseUcs(catid)   # data-test 没打标 → 期望空列表但信号必须走通

        # 改标写回：克隆库里取一个真实 fileId，setUcsLabel 应写 manual 并返回结果文案
        conn = db.connect(str(_clone / "library.db"))
        frow = conn.execute("SELECT id, filename FROM files ORDER BY id LIMIT 1").fetchone()
        conn.close()
        fid = int(frow["id"]) if frow else 1
        relabel_msg = backend.setUcsLabel(fid, "AIRBlow")
        print(f"[relabel] file={frow['filename'] if frow else '?'} msg='{relabel_msg}'")
        assert "已改标" in relabel_msg and "source=manual" in relabel_msg, f"改标写回失败：{relabel_msg}"
        state["relabel_ok"] = True

        # 收藏（持久化到 SOUNDCATCHER_APPDATA 临时目录）
        assert backend.isFavorite(path) is False, "初始不应已收藏"
        assert backend.toggleFavorite(path, "Windows Recycle.wav", 1) is True, "收藏应成功"
        assert backend.isFavorite(path) is True, "收藏后 isFavorite 应为 True"
        assert len(backend.favorites) == 1
        # 收藏夹导出（md 到临时导出目录；SOUNDCATCHER_EXPORT_DIR 覆盖默认 Downloads）
        os.environ["SOUNDCATCHER_EXPORT_DIR"] = tempfile.mkdtemp(prefix="sc-export-")
        msg = backend.exportFavorites("md")
        print(f"[export] {msg}")
        assert "已导出" in msg and ".md" in msg, f"导出失败：{msg}"
        export_dir = Path(os.environ["SOUNDCATCHER_EXPORT_DIR"])
        mds = list(export_dir.glob("*.md"))
        assert mds and path in mds[0].read_text(encoding="utf-8"), "导出文件缺失或缺少收藏路径"
        state["export_ok"] = True
        assert backend.toggleFavorite(path, "Windows Recycle.wav", 1) is False, "再点应取消"
        assert backend.toggleFavorite(path, "Windows Recycle.wav", 1) is True
        state["fav_ok"] = True
        print(f"[fav] toggled/is_fav/count: "
              f"{backend.isFavorite(path)}/{len(backend.favorites)}")

        # 收藏导入：路径列表文件 → importFavorites 解析入库（已包含去重/置顶语义）
        imp = Path(tempfile.mkdtemp(prefix="sc-imp-")) / "import.txt"
        imp.write_text("# list\nc:/imp/one.wav\nc:/imp/two.wav\nc:/imp/one.wav\n", encoding="utf-8")
        imp_msg = backend.importFavorites(str(imp))
        print(f"[import] {imp_msg}")
        assert "已导入 2 条新收藏" in imp_msg, f"导入失败：{imp_msg}"
        assert backend.isFavorite("c:/imp/one.wav") is True, "导入的 one.wav 应已收藏"
        assert backend.isFavorite("c:/imp/two.wav") is True, "导入的 two.wav 应已收藏"
        state["import_ok"] = True

        # 保存搜索（持久化 + 去重 + 移除）
        backend.saveSearch("glass breaking", "semantic")
        backend.saveSearch("闹钟铃声", "hybrid")
        backend.saveSearch("glass breaking", "semantic")  # 重复 → 去重置顶
        n = len(backend.savedSearches)
        assert n == 2, f"保存搜索应去重为 2 条，实际 {n}"
        assert backend.removeSavedSearch("glass breaking", "semantic") is True
        assert len(backend.savedSearches) == 1
        state["saved_ok"] = True
        print(f"[saved] count={n} after-remove={len(backend.savedSearches)}")

        # 后台扫描任务（写锁护栏 + 子进程；data-test 已含 C:\Windows\\Media 80 文件
        # → 增量全 skip，秒级结束；同时验证与 GUI 只读并存）
        msg = backend.startScan(r"C:\Windows\Media")
        print(f"[scan] start: {msg}")
        assert "扫描" in msg and "目录不存在" not in msg, f"扫描启动失败：{msg}"
        # 二次启动应被护栏拒绝（已有扫描在运行）
        msg2 = backend.startScan(r"C:\Windows\Media")
        print(f"[scan] double-start: {msg2}")
        assert "已有扫描" in msg2, "并发启动应被拒绝（坑 11 护栏）"
        state["scan_ok"] = True

    def finish() -> None:
        try:
            print("--- SMOKE RESULT ---")
            print(state)
            assert state["ready"], "库未就绪（模型加载失败或索引库缺失）"
            assert state["results"] is not None and len(state["results"]) > 0, "没有检索结果"
            assert state["wave"] and state["wave"] > 100, "波形未生成"
            assert not state["failed"], f"搜索失败：{state['failed']}"
            assert state["browse"] is not None, "UCS 浏览信号未返回"
            assert state["fav_ok"], "收藏功能未通过"
            assert state["saved_ok"], "保存搜索功能未通过"
            assert state["export_ok"], "收藏夹导出未通过"
            assert state["relabel_ok"], "改标写回（setUcsLabel）未通过"
            assert state["import_ok"], "收藏导入（importFavorites）未通过"
            assert state["scan_ok"], "扫描任务启动未通过"
            st = backend.scanState
            print(f"[scan] final state={st} | {backend.scanMessage}")
            assert st in ("done", "failed"), f"扫描未在窗口内结束：{st}"
            print("SMOKE OK")
        finally:
            backend.shutdown()
            app.quit()

    QTimer.singleShot(15000, run)   # 留足 CLAP 双塔 + 库加载时间
    QTimer.singleShot(45000, finish)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())