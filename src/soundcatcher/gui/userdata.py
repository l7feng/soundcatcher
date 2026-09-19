"""GUI 用户数据持久化：收藏（Favorites）+ 保存搜索（Saved Searches）。

存放位置：
- Windows：``%APPDATA%/SoundCatcher/state.json``（如 ``C:\\Users\\<user>\\AppData\\Roaming\\SoundCatcher\\state.json``）
- 非 Windows：``~/.config/SoundCatcher/state.json``
- 覆盖：``SOUNDCATCHER_APPDATA`` 环境变量（指定**目录**，state.json 在其下；测试/便携用）

设计要点：
- 量小（收藏 ≤ ``MAX_FAVORITES``、保存搜索 ≤ ``MAX_SAVED``），UI 线程直接读写，
  不加锁——GUI 单例锁（QLockFile）已保证同一数据目录只有一个实例。
- **原子写**：写 ``state.json.tmp`` 后 ``os.replace``，崩溃不留半写文件。
- 损坏/缺失静默回退空列表，GUI 不崩。

数据形状::

    {
      "version": 1,
      "favorites": [{"path": "...", "filename": "...", "fileId": 123, "savedAt": 1726...}],
      "savedSearches": [{"query": "...", "mode": "semantic", "savedAt": 1726...}]
    }

favorites 按 ``path`` 去重（重复保存 = 置顶 + 更新 savedAt）；savedSearches 按
``query + mode`` 去重。
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
from datetime import datetime
from pathlib import Path

MAX_FAVORITES = 200
MAX_SAVED = 100

VERSION = 1

EXPORT_FORMATS = ("md", "csv", "m3u", "wavlist")


def _to_float(v) -> float | None:
    """宽松把字符串/数字转 float（空值/坏值 → None，供导入时回退当前时间）。"""
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def default_state_path() -> Path:
    """决定 state.json 的默认落点（``SOUNDCATCHER_APPDATA`` 可覆盖目录）。"""
    env = os.environ.get("SOUNDCATCHER_APPDATA")
    if env:
        return Path(env).expanduser().resolve() / "state.json"
    if os.name == "nt" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"])
    else:
        base = Path.home() / ".config"
    return base / "SoundCatcher" / "state.json"


class UserDataStore:
    """收藏 + 保存搜索的 JSON 存储（线程内简单对象，不需要迁移）。"""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_state_path()
        self._favs: list[dict] = []
        self._saved: list[dict] = []
        self._load()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._favs = [
                f for f in data.get("favorites", [])
                if isinstance(f, dict) and f.get("path")
            ][:MAX_FAVORITES]
            self._saved = [
                s for s in data.get("savedSearches", [])
                if isinstance(s, dict) and s.get("query") and s.get("mode")
            ][:MAX_SAVED]
        except (json.JSONDecodeError, OSError) as exc:
            # 损坏状态文件：不崩 GUI，回退空；下次保存时覆盖修复
            self._favs, self._saved = [], []
            import logging
            logging.getLogger(__name__).warning("state.json 读取失败（已回退空）：%s", exc)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(
                {"version": VERSION, "favorites": self._favs, "savedSearches": self._saved},
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------
    # 收藏
    # ------------------------------------------------------------------

    @property
    def favorites(self) -> list[dict]:
        """最新在前。返回副本，避免调用方改坏内部状态。"""
        return [dict(f) for f in self._favs]

    def is_favorite(self, path: str) -> bool:
        return any(f["path"] == path for f in self._favs)

    def toggle_favorite(self, path: str, filename: str, file_id: int | None = None) -> bool:
        """切状态；返回切换后的收藏态（True = 已收藏）。"""
        existing = next((f for f in self._favs if f["path"] == path), None)
        if existing is not None:
            self._favs.remove(existing)
            self._save()
            return False
        self._favs.insert(
            0,
            {
                "path": path,
                "filename": filename or Path(path).name,
                "fileId": file_id,
                "savedAt": time.time(),
            },
        )
        del self._favs[MAX_FAVORITES:]
        self._save()
        return True

    def remove_favorite(self, path: str) -> bool:
        before = len(self._favs)
        self._favs = [f for f in self._favs if f["path"] != path]
        if len(self._favs) != before:
            self._save()
            return True
        return False

    # ------------------------------------------------------------------
    # 收藏夹导出（不改变状态，生成新文件）
    # ------------------------------------------------------------------

    def export_favorites(self, out_dir: str | Path, fmt: str = "md") -> Path:
        """收藏夹导出为 ``fmt``（md | csv | m3u），返回生成的文件路径。

        - md：Obsidian 友好的 Markdown 表格（路径写成双链引用的纯文本，见下）
        - csv：UTF-8 BOM（Excel 打开中文不乱码）+ 双引号包裹
        - m3u：音频播放列表（EXTM3U/EXTINF + 本地路径）
        - wavlist：Soundminer / BaseHead 约定的"逐行绝对路径"清单（无头部、无注释）

        生成文件名带时间戳 ``SoundCatcher-favorites-YYYYMMDD-HHMMSS.<ext>``。
        """
        if fmt not in EXPORT_FORMATS:
            raise ValueError(f"不支持的导出格式：{fmt}（可选 {EXPORT_FORMATS}）")
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = out / f"SoundCatcher-favorites-{stamp}.{fmt}"

        favs = self._favs
        if fmt == "md":
            lines = [
                "# SoundCatcher 收藏夹（Favorites）",
                "",
                f"- 导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"- 条数：{len(favs)}",
                "",
                "| # | 文件名 | 路径 | 收藏时间 |",
                "| --- | --- | --- | --- |",
            ]
            for i, f in enumerate(favs, 1):
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime(f.get("savedAt", 0)))
                lines.append(
                    f"| {i} | {f['filename']} | `{f['path']}` | {when} |"
                )
            dest.write_text("\n".join(lines) + "\n", encoding="utf-8")

        elif fmt == "csv":
            with open(dest, "w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["filename", "path", "savedAt"])
                for f in favs:
                    writer.writerow([f["filename"], f["path"], f.get("savedAt", "")])

        elif fmt == "m3u" or fmt == "wavlist":
            # wavlist：纯逐行路径（无 #EXTM3U / EXTINF），供 Soundminer/BaseHead 批量导入
            if fmt == "wavlist":
                lines = [f["path"] for f in favs]
            else:  # m3u —— 只写本地文件路径（外部播放器可跨平台用），EXTINF 带时长为空
                lines = ["#EXTM3U"]
                for f in favs:
                    lines.append(f"#EXTINF:0,{f['filename']}")
                    lines.append(f["path"])
            dest.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

        return dest

    # ------------------------------------------------------------------
    # 收藏夹导入（md / csv / m3u / 纯路径列表）
    # ------------------------------------------------------------------

    def import_favorites(self, path: str | Path, fmt: str | None = None) -> int:
        """从导出文件或纯文本路径列表导入收藏；返回**新增**条数。

        - 自动按扩展名识别 ``fmt``（md / csv / m3u / txt）；不识别则退化为
          "每行一个路径"的纯文本解析。
        - 已存在的路径丢弃后置顶（同 toggle 语义：重复导入 = 刷新收藏时间）；
          新路径插入最前，总量裁剪到 MAX_FAVORITES 并原子落盘。
        - 解析兼容导出时生成的格式（csv 表头 / md 表格带反引号路径 / m3u 两行对）。
        - 文件不可读/损坏抛异常由调用方（backend.importFavorites）兜底提示。
        """
        src = Path(path)
        text = src.read_text(encoding="utf-8-sig", errors="replace")
        fmt = (fmt or src.suffix.lstrip(".")).lower()
        entries = self._parse_favorites(text, fmt)
        if not entries:
            return 0
        added = 0
        now = time.time()
        # 文件行序 = 新→旧；倒序插入到 0，保证首行（最新）最终在列表顶部
        for e in reversed(entries):
            p = e["path"].strip("\"'")
            if not p:
                continue
            existing = next((f for f in self._favs if f["path"] == p), None)
            if existing is not None:
                self._favs.remove(existing)
            else:
                added += 1
            self._favs.insert(
                0,
                {
                    "path": p,
                    "filename": e.get("filename") or Path(p).name,
                    "fileId": e.get("fileId"),
                    "savedAt": e.get("savedAt") or now,
                },
            )
        del self._favs[MAX_FAVORITES:]
        self._save()
        return added

    @staticmethod
    def _parse_favorites(text: str, fmt: str) -> list[dict]:
        """按格式把文本解析为 ``[{"path", "filename"?, "savedAt"?}, ...]``（已去重）。"""
        entries: list[dict] = []

        if fmt == "csv":
            try:
                rows = list(csv.DictReader(io.StringIO(text)))
            except csv.Error:
                rows = []
            for r in rows:
                p = (r.get("path") or "").strip().strip("\"'")
                if not p:
                    continue
                saved = r.get("savedAt") or ""
                entries.append({
                    "path": p,
                    "filename": (r.get("filename") or "").strip(),
                    "savedAt": _to_float(saved),
                })

        elif fmt == "m3u":
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            i = 0
            while i < len(lines):
                ln = lines[i]
                if ln.startswith("#EXTINF"):
                    name = ln.split(",", 1)[1].strip() if "," in ln else ""
                    i += 1
                    if i < len(lines) and not lines[i].startswith("#"):
                        entries.append({"path": lines[i], "filename": name})
                elif not ln.startswith("#"):
                    entries.append({"path": ln})
                i += 1

        else:  # md / txt / 其他 → 行级解析
                if fmt == "md":
                    # Obsidian 表行：| 1 | 文件名 | `path` | 时间 |；非 | 行（标题/元信息）忽略
                    for raw in text.splitlines():
                        ln = raw.strip()
                        if not ln.startswith("|"):
                            continue
                        for cell in ln.strip("|").split("|"):
                            c = cell.strip()
                            if c.startswith("`") and c.endswith("`") and len(c) > 2:
                                entries.append({"path": c[1:-1]})
                                break
                else:
                    # txt / 未知扩展名 → 每行一个路径（# / // 为注释）
                    for raw in text.splitlines():
                        ln = raw.strip()
                        if not ln or ln.startswith("#") or ln.startswith("//"):
                            continue
                        entries.append({"path": ln})

        # 去重（保留首次出现顺序）+ 去除无效路径
        seen: set[str] = set()
        out: list[dict] = []
        for e in entries:
            p = e["path"].strip("\"'")
            if not p or p in seen:
                continue
            seen.add(p)
            e["path"] = p
            out.append(e)
        return out

    # ------------------------------------------------------------------
    # 保存搜索
    # ------------------------------------------------------------------

    @property
    def saved_searches(self) -> list[dict]:
        return [dict(s) for s in self._saved]

    def add_saved_search(self, query: str, mode: str) -> None:
        query = query.strip()
        mode = mode.strip() or "semantic"
        if not query:
            return
        self._saved = [s for s in self._saved if not (s["query"] == query and s["mode"] == mode)]
        self._saved.insert(0, {"query": query, "mode": mode, "savedAt": time.time()})
        del self._saved[MAX_SAVED:]
        self._save()

    def remove_saved_search(self, query: str, mode: str) -> bool:
        before = len(self._saved)
        self._saved = [s for s in self._saved if not (s["query"] == query and s["mode"] == mode)]
        if len(self._saved) != before:
            self._save()
            return True
        return False