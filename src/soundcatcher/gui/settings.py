"""GUI 设置持久化：主题 / 语言 / 可改路径 / 侧栏宽度（``settings.json``）。

与 ``userdata.py``（收藏+保存搜索）分开的理由：职责不同 ——
``state.json`` 是**用户内容**，``settings.json`` 是**应用偏好**。混在一起会让
「重置偏好」连带删掉收藏。

存放位置（可被 ``SOUNDCATCHER_APPDATA`` 覆盖目录，与 state.json 同目录）：
- Windows：``%APPDATA%/SoundCatcher/settings.json``
- 非 Windows：``~/.config/SoundCatcher/settings.json``

数据形状::

    {
      "version": 1,
      "ui":    { "theme": "dark", "language": "zh", "sidebarWidth": 320 },
      "paths": { "dataHome": null, "stateDir": null, "modelsDir": null,
                 "catalogDir": null, "exportDir": null }
    }

``paths`` 里 ``null`` = 用工程默认（见 ``config.py`` 的解析优先级）。
**优先级**：环境变量 > settings.json > 工程默认 —— 保证既有 ``SOUNDCATCHER_*``
环境变量语义不被破坏（测试/便携场景仍可强制覆盖）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

VERSION = 1

# 允许用户改的 5 条路径（key → 中文说明）
PATH_KEYS: dict[str, str] = {
    "dataHome": "数据目录（library.db / faiss 索引 / UCS 派生数据）",
    "stateDir": "用户数据目录（收藏、保存搜索）",
    "modelsDir": "模型目录（CLAP 双塔 + 翻译模型）",
    "catalogDir": "UCS 静态语料（753 类官方字典）",
    "exportDir": "收藏夹导出目录",
}

MAX_SIDEBAR = 640
MIN_SIDEBAR = 260


def settings_path() -> Path:
    """settings.json 落点（``SOUNDCATCHER_APPDATA`` 可覆盖目录）。"""
    env = os.environ.get("SOUNDCATCHER_APPDATA")
    if env:
        return Path(env).expanduser().resolve() / "settings.json"
    if os.name == "nt" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"])
    else:
        base = Path.home() / ".config"
    return base / "SoundCatcher" / "settings.json"


class Settings:
    """应用偏好（小对象，UI 线程读写，原子落盘）。"""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else settings_path()
        self.theme: str = "dark"          # light | dark | system
        self.language: str = "zh"         # zh | en
        self.sidebar_width: int = 320
        self.paths: dict[str, str | None] = {k: None for k in PATH_KEYS}
        self._load()

    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # 损坏不崩 GUI，回退默认；下次保存时覆盖修复
            import logging
            logging.getLogger(__name__).warning("settings.json 读取失败（已回退默认）：%s", self.path)
            return

        ui = data.get("ui") or {}
        if ui.get("theme") in ("light", "dark", "system"):
            self.theme = ui["theme"]
        if ui.get("language") in ("zh", "en"):
            self.language = ui["language"]
        try:
            w = int(ui.get("sidebarWidth", self.sidebar_width))
            self.sidebar_width = max(MIN_SIDEBAR, min(MAX_SIDEBAR, w))
        except (TypeError, ValueError):
            pass

        raw_paths = data.get("paths") or {}
        for k in PATH_KEYS:
            v = raw_paths.get(k)
            if isinstance(v, str) and v.strip():
                self.paths[k] = v.strip()

    def save(self) -> None:
        """原子写（tmp + os.replace），崩溃不留半写文件。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(
                {
                    "version": VERSION,
                    "ui": {
                        "theme": self.theme,
                        "language": self.language,
                        "sidebarWidth": self.sidebar_width,
                    },
                    "paths": self.paths,
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------

    def apply_to_environ(self) -> None:
        """把已保存的路径偏好注入 ``SOUNDCATCHER_*`` 环境变量（供 config 解析）。

        **只在环境变量未显式设置时注入** —— 保证「环境变量 > settings.json」优先级。
        必须在 ``Config.default()`` 之前调用（app.main 启动最早期）。
        """
        mapping = {
            "dataHome": "SOUNDCATCHER_DATA_HOME",
            "stateDir": "SOUNDCATCHER_APPDATA",
            "modelsDir": "SOUNDCATCHER_MODELS",
            "catalogDir": "SOUNDCATCHER_CATALOG",
            "exportDir": "SOUNDCATCHER_EXPORT_DIR",
        }
        for key, env in mapping.items():
            val = self.paths.get(key)
            if val and not os.environ.get(env):
                os.environ[env] = val

    def effective_paths(self) -> dict[str, str]:
        """返回 5 条路径的**实际生效值**（供设置面板显示）。"""
        from ..config import Config
        cfg = Config.default()
        env_map = {
            "dataHome": os.environ.get("SOUNDCATCHER_DATA_HOME"),
            "stateDir": os.environ.get("SOUNDCATCHER_APPDATA"),
            "modelsDir": os.environ.get("SOUNDCATCHER_MODELS"),
            "catalogDir": os.environ.get("SOUNDCATCHER_CATALOG"),
            "exportDir": os.environ.get("SOUNDCATCHER_EXPORT_DIR"),
        }
        defaults = {
            "dataHome": str(cfg.data_dir),
            "stateDir": str(self.path.parent),
            "modelsDir": str(cfg.models_dir),
            "catalogDir": str(cfg.catalog_dir),
            "exportDir": str(Path.home() / "Downloads"),
        }
        out: dict[str, str] = {}
        for k in PATH_KEYS:
            out[k] = env_map.get(k) or defaults[k]
        return out


# ---------------------------------------------------------------------------
# 路径迁移（改路径时把旧数据搬过去）
# ---------------------------------------------------------------------------

class MigrateResult:
    """迁移结果：给 UI 汇报用的小结构。"""

    def __init__(self, key: str, old: str, new: str, mode: str):
        self.key = key
        self.old = old
        self.new = new
        self.mode = mode          # move | copy | none
        self.moved = 0            # 搬过去的条目数
        self.skipped: list[str] = []
        self.error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def summary(self) -> str:
        if self.error:
            return f"迁移失败：{self.error}"
        if self.mode == "none":
            return "无需迁移（旧目录不存在或为空）"
        verb = "移动" if self.mode == "move" else "复制"
        s = f"已{verb} {self.moved} 个条目：{self.old} → {self.new}"
        if self.skipped:
            s += f"（跳过 {len(self.skipped)} 个）"
        return s


def _is_subpath(child: Path, parent: Path) -> bool:
    """child 是否位于 parent 之内（用于拒绝「新路径在旧路径里面」这种套娃）。"""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def migrate_path(key: str, old: str | Path | None, new: str | Path,
                 *, mode: str = "move", dry_run: bool = False) -> MigrateResult:
    """把 ``old`` 目录内容搬到 ``new``。

    - ``mode="move"``：``shutil.move`` 逐条目（**跨盘也安全**，不用 rmtree）
    - ``mode="copy"``：``shutil.copytree``，旧数据保留
    - 旧目录不存在 / 为空 → 直接返回 ``mode="none"``（改路径不需要搬东西）

    安全约束（拒绝执行并返回 error）：
    - ``new`` 在 ``old`` 之内或反之（套娃会造成搬一半找不到东西）
    - ``new`` 已存在且非空（避免与既有数据混淆）
    - ``new`` 不可写

    注意：**不用 ``shutil.rmtree`` 删旧目录** —— 只会把里面东西逐条移走，
    留下空壳。调用方确认成功后再决定是否清理（本函数不做删除）。
    """
    res = MigrateResult(key, str(old or ""), str(new), mode)
    if not old:
        res.mode = "none"
        return res
    src = Path(old)
    dst = Path(new)
    if src.resolve() == dst.resolve():
        res.mode = "none"
        return res
    if not src.exists() or not any(src.iterdir()):
        res.mode = "none"
        return res
    if _is_subpath(dst, src) or _is_subpath(src, dst):
        res.error = "新旧路径互相包含，拒绝迁移（会造成数据丢失）"
        return res
    if dst.exists() and any(dst.iterdir()):
        res.error = f"目标目录非空：{dst}（请换一个空目录，或先手工清理）"
        return res

    if dry_run:
        res.moved = len(list(src.iterdir()))
        return res

    import shutil
    try:
        dst.mkdir(parents=True, exist_ok=True)
        for item in sorted(src.iterdir()):
            target = dst / item.name
            if target.exists():
                res.skipped.append(item.name)
                continue
            if mode == "move":
                shutil.move(str(item), str(target))
            else:
                if item.is_dir():
                    shutil.copytree(item, target)
                else:
                    shutil.copy2(item, target)
            res.moved += 1
    except OSError as exc:
        res.error = str(exc)
    return res
