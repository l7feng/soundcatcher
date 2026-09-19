"""运行配置与路径解析。

数据根目录（``home``）优先级：

1. 环境变量 ``SOUNDCATCHER_HOME``
2. 默认：项目根目录（开发期）

模型根目录（``models_dir``）优先级：

1. 环境变量 ``SOUNDCATCHER_MODELS``（显式指定，便携/多库共存用）
2. 工程层 ``<home>/../models``（**现行布局**：models 已移出 ``SoundCatcher/``，
   置于工程目录 ``Sound-library/`` 下，与代码仓分离，避免 1GB 二进制污染 git 仓）
3. 仓内 ``<home>/models``（历史布局，兼容旧环境）

``home`` 下布局：

- ``data/library.db``    SQLite 元数据
- ``data/index/``        faiss 向量索引
- ``catalog/``           UCS 静态语料（官方全表 + 中文侧）

``models_dir`` 下布局（位于 ``Sound-library/models/``）：

- ``onnx_audio_model.onnx`` / ``onnx_text_model.onnx``  CLAP 双塔
- ``opus-mt-zh-en/``                                    中→英翻译桥
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_HOME = "SOUNDCATCHER_HOME"
ENV_MODELS = "SOUNDCATCHER_MODELS"


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
        return self.home / "data"

    @property
    def catalog_dir(self) -> Path:
        """UCS 静态语料（官方全表 + 中文侧），随应用分发。"""
        return self.home / "catalog"

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
