"""UserDataStore 纯逻辑测试：收藏 + 保存搜索的持久化（无需 Qt/GUI）。

用法::

    python tests/test_userdata.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from soundcatcher.gui.userdata import MAX_FAVORITES, MAX_SAVED, UserDataStore  # noqa: E402


def main() -> int:
    tmp = Path(tempfile.mkdtemp()) / "state.json"

    # 空库
    s = UserDataStore(tmp)
    assert s.favorites == [], "初始收藏应为空"
    assert s.saved_searches == [], "初始保存搜索应为空"
    assert not s.is_favorite("a.wav")

    # 收藏开/关/查
    assert s.toggle_favorite("a.wav", "a.wav", 1) is True, "toggle 开启应返回 True"
    assert s.is_favorite("a.wav")
    assert len(s.favorites) == 1
    assert s.favorites[0]["path"] == "a.wav" and s.favorites[0]["fileId"] == 1
    assert s.toggle_favorite("a.wav", "a.wav", 1) is False, "toggle 关闭应返回 False"
    assert not s.is_favorite("a.wav")

    # 持久化：重启实例读回
    s.toggle_favorite("x/1.wav", "1.wav", 7)
    s.toggle_favorite("x/2.wav", "2.wav", None)
    s2 = UserDataStore(tmp)
    assert len(s2.favorites) == 2, "收藏应从磁盘读回"
    assert s2.favorites[0]["path"] == "x/2.wav", "最新收藏应在最前"

    # remove
    assert s2.remove_favorite("x/1.wav") is True
    assert s2.remove_favorite("x/1.wav") is False, "重复移除应返回 False"

    # 保存搜索：去重 + 置顶 + 持久化
    s.add_saved_search("glass breaking", "semantic")
    s.add_saved_search("闹钟铃声", "hybrid")
    s.add_saved_search("glass breaking", "semantic")   # 重复 → 仅更新
    s3 = UserDataStore(tmp)
    assert len(s3.saved_searches) == 2, "重复保存应去重"
    assert s3.saved_searches[0]["query"] == "glass breaking"

    # remove
    assert s3.remove_saved_search("glass breaking", "semantic") is True
    s4 = UserDataStore(tmp)
    assert len(s4.saved_searches) == 1
    assert s4.saved_searches[0]["query"] == "闹钟铃声"

    # 上限裁剪
    s5 = UserDataStore(tmp)
    for i in range(MAX_FAVORITES + 30):
        s5.toggle_favorite(f"f{i}.wav", f"f{i}.wav", i)
    assert len(s5.favorites) == MAX_FAVORITES, f"收藏应裁剪到 {MAX_FAVORITES}"
    for i in range(MAX_SAVED + 20):
        s5.add_saved_search(f"q{i}", "semantic")
    assert len(s5.saved_searches) == MAX_SAVED, f"保存搜索应裁剪到 {MAX_SAVED}"

    # 损坏文件容错
    tmp.write_text("{broken json", encoding="utf-8")
    s6 = UserDataStore(tmp)
    assert s6.favorites == [] and s6.saved_searches == [], "损坏 state.json 应回退空"

    # 原子写产物
    assert not (tmp.with_suffix(".json.tmp")).exists(), ".tmp 残留应不存在"

    # ---- 收藏夹导出：md / csv / m3u / wavlist ----
    s7 = UserDataStore(tmp)
    s7.toggle_favorite("x/铃铛.wav", "铃铛.wav", 3)
    s7.toggle_favorite("x/glass.wav", "glass.wav", 5)
    outdir = Path(tempfile.mkdtemp()) / "export"
    for fmt, suffix in (("md", ".md"), ("csv", ".csv"), ("m3u", ".m3u"), ("wavlist", ".wavlist")):
        dest = s7.export_favorites(outdir, fmt)
        assert dest.exists() and dest.suffix == suffix, f"{fmt} 导出文件缺失/后缀错：{dest}"
        text = dest.read_text(encoding="utf-8-sig" if fmt == "csv" else "utf-8")
        assert "铃铛.wav" in text and "glass.wav" in text, f"{fmt} 导出缺条目"
        assert "x/铃铛.wav" in text, f"{fmt} 导出应含完整路径"
    # md 应有表格头；m3u 应有 EXTM3U；csv 应含表头
    mds = sorted(outdir.glob("*.md"))[-1].read_text(encoding="utf-8")
    assert "| 文件名 | 路径 | 收藏时间 |" in mds
    m3u = sorted(outdir.glob("*.m3u"))[-1].read_text(encoding="utf-8")
    assert m3u.startswith("#EXTM3U")
    csv_text = sorted(outdir.glob("*.csv"))[-1].read_text(encoding="utf-8-sig")
    assert csv_text.startswith("filename,path,savedAt")
    # wavlist：纯逐行路径（无头部/无注释），首行即路径
    wl = sorted(outdir.glob("*.wavlist"))[-1].read_text(encoding="utf-8")
    wl_lines = [ln for ln in wl.splitlines() if ln.strip()]
    assert not wl.startswith("#"), "wavlist 不应有头部/注释"
    assert all(not ln.startswith("#") for ln in wl_lines), f"wavlist 应为纯路径：{wl_lines}"
    assert set(wl_lines) == {"x/glass.wav", "x/铃铛.wav"}, f"wavlist 内容不符：{wl_lines}"
    # wavlist 可被回读（纯路径解析分支）
    s_wl = UserDataStore(Path(tempfile.mkdtemp()) / "wl.json")
    assert s_wl.import_favorites(sorted(outdir.glob("*.wavlist"))[-1]) == 2, "wavlist 应可回读 2 条"
    # 非法格式应报错
    try:
        s7.export_favorites(outdir, "txt")
        raise AssertionError("非法格式应抛 ValueError")
    except ValueError:
        pass
    # 空收藏导出也应生成文件（0 条）
    s8 = UserDataStore(tmp)
    empty_dest = s8.export_favorites(outdir, "md")
    assert empty_dest.exists()

    print("USERDATA OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())