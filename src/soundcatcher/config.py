"""运行配置与路径解析。

数据根目录（``home``）优先级：

1. 环境变量 ``SOUNDCATCHER_HOME``
2. 默认：项目根目录（开发期）

数据目录（``data_dir``）优先级：

1. 环境变量 ``SOUNDCATCHER_DATA_HOME``（GUI 设置面板写入）
2. ``<home>/data``

模型根目录（``models_dir``）优先级：

1. 环境变量 ``SOUNDCATCHER_MODELS``（显式指定，便携/多库共存用）
2. 工程层 ``<home>/../models``（便携 / 多库共存用；现行不落在此）
3. 仓内 ``<home>/models``（**现行布局**：2026-09-22 起 models 回到仓内
   ``SoundCatcher/models/``，由 ``.gitignore`` 排除 —— 与 ``data/`` 同款处理：
   「仓文件夹＝项目文件夹」，靠 .gitignore 划界，而非把资产挪出仓外）

UCS 静态语料目录（``catalog_dir``）优先级：

1. 环境变量 ``SOUNDCATCHER_CATALOG``（GUI 设置面板写入）
2. ``<home>/catalog``（工程默认）

``home`` 下布局：

- ``catalog/``           UCS 静态语料（官方全表 + 中文侧，只读「原料」）

``data_dir`` 下布局：

- ``library.db``    SQLite 元数据
- ``index/``        faiss 向量索引
- ``ucs/``          UCS 派生数据（原型矩阵 + 条目元数据，可重建）

``models_dir`` 下布局（现行位于 ``SoundCatcher/models/``）：

- ``onnx_audio_model.onnx`` / ``onnx_text_model.onnx``  CLAP 双塔
- ``opus-mt-zh-en/``                                    中→英翻译桥

**注意**：``data_dir`` / ``catalog_dir`` 都会读环境变量（GUI 设置面板通过写
``SOUNDCATCHER_*`` 生效），因此属性是**动态**的 —— 不要缓存到模块级常量。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_HOME = "SOUNDCATCHER_HOME"
ENV_MODELS = "SOUNDCATCHER_MODELS"
ENV_CATALOG = "SOUNDCATCHER_CATALOG"


def _resolve_models_dir(home: Path) -> Path:
    """按优先级解析模型目录（见模块 docstring）。"""
    env = os.environ.get(ENV_MODELS)
    if env:
        return Path(env).expanduser().resolve()
    # 现行布局：models 在工程层（home 的上一级），与代码仓 SoundCatcher/ 平级
    sibling = home.parent / "models"
    if sibling.is_dir():
        return sibling
    # 历史布局：models 在仓内
    return home / "models"


def _resolve_catalog_dir(home: Path) -> Path:
    """解析 UCS 静态语料目录（753 类官方字典）。

    优先级：``SOUNDCATCHER_CATALOG`` > ``<home>/catalog``（工程默认）。
    注意：语料**不在 ``data/`` 下** —— 它是只读「原料」而非派生产物，
    留在 default 位置可保证「删掉 data/ 即可完全重置」的语义不被破坏。
    """
    env = os.environ.get(ENV_CATALOG)
    if env:
        return Path(env).expanduser().resolve()
    return home / "catalog"


@dataclass
class Config:
    """运行时路径配置。"""

    home: Path
    models_dir: Path

    @classmethod
    def default(cls) -> "Config":
        env = os.environ.get(ENV_HOME)
        if env:
            home = Path(env).expanduser().resolve()
        else:
            home = Path(__file__).resolve().parents[2]
        return cls(home=home, models_dir=_resolve_models_dir(home))

    @property
    def translator_dir(self) -> Path:
        """离线中→英翻译模型目录（OPUS-MT）。"""
        return self.models_dir / "opus-mt-zh-en"

    @property
    def data_dir(self) -> Path:
        """数据目录：可用 ``SOUNDCATCHER_DATA_HOME`` 覆盖（GUI 设置面板写入该变量）。"""
        env = os.environ.get("SOUNDCATCHER_DATA_HOME")
        if env:
            return Path(env).expanduser().resolve()
        return self.home / "data"

    @property
    def catalog_dir(self) -> Path:
        """UCS 静态语料（官方全表 + 中文侧），随应用分发。

        可用 ``SOUNDCATCHER_CATALOG`` 覆盖（GUI 设置面板）；**默认不在 data/ 下**。
        """
        return _resolve_catalog_dir(self.home)

    @property
    def ucs_dir(self) -> Path:
        """UCS 派生数据：原型矩阵 + 条目元数据（`ucs init` 生成，可重建）。"""
        return self.data_dir / "ucs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "library.db"

    @property
    def index_path(self) -> Path:
        return self.data_dir / "index" / "vectors.faiss"

    def ensure(self) -> None:
        """确保必要目录存在。"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
