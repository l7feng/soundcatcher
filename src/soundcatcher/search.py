"""检索核心。

三种查询方式：

- **语义（AI）**：文本 → CLAP 文本塔 → 512 维向量 → faiss 内积检索
- **以声搜声**：参考音频 → CLAP 音频塔 → 同一空间 → faiss 检索
- **关键词**：SQLite FTS5（文件名 / 路径 / 标签）

混合模式把语义分与 BM25 分归一化后加权融合，兼顾"描述性查询"与"精确命名查询"。

CLAP 文本塔只认英文，因此**含中日韩字符的查询会先用离线翻译桥（``OpusTranslator``）
转成英文再做语义检索**（关键词检索仍用原文，因为文件名本身可能就是中文）。
翻译器由外部通过 ``translator_factory`` 惰性注入——只有真的出现中文查询时才加载。
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import db
from .audio import load_for_embedding
from .embedder import ClapEmbedder
from .indexer import VectorIndex
from .translator import OpusTranslator, has_cjk

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """一条检索结果。"""

    file_id: int
    path: str
    filename: str
    duration: float
    score: float
    source: str  # semantic | keyword | hybrid
    tags: list[str]

    @property
    def duration_str(self) -> str:
        total = int(round(self.duration or 0))
        return f"{total // 60}:{total % 60:02d}"


def _normalize(scores: np.ndarray) -> np.ndarray:
    """把分数压到 [0,1]（min-max），全等时返回 1。"""
    if scores.size == 0:
        return scores
    lo, hi = float(scores.min()), float(scores.max())
    if hi - lo < 1e-9:
        return np.ones_like(scores)
    return (scores - lo) / (hi - lo)


class Searcher:
    """组合 faiss 与 SQLite 的检索器。"""

    def __init__(
        self,
        conn: sqlite3.Connection,
        index: VectorIndex,
        embedder: ClapEmbedder,
        translator_factory: Callable[[], OpusTranslator] | None = None,
    ):
        self.conn = conn
        self.index = index
        self.embedder = embedder
        self._translator_factory = translator_factory
        self._translator: OpusTranslator | None = None
        self.last_translation: str | None = None

    # -- 中文查询预处理 ----------------------------------------------------

    def _prepare_query(self, query: str) -> str:
        """含中日韩字符时经翻译桥转英文；否则原样返回。

        翻译加载失败或翻译结果为空时静默回退原文，绝不让检索因翻译挂掉。
        """
        self.last_translation = None
        if not has_cjk(query) or self._translator_factory is None:
            return query
        try:
            if self._translator is None:
                self._translator = self._translator_factory()
            english = self._translator.translate(query).strip()
        except Exception:  # noqa: BLE001
            logger.exception("查询翻译失败，回退原文检索")
            return query
        if english:
            self.last_translation = english
            logger.debug("查询翻译：%s → %s", query, english)
            return english
        return query

    # -- 基础查询 ----------------------------------------------------------

    def _fetch(self, file_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()

    def _to_result(self, file_id: int, score: float, source: str) -> SearchResult | None:
        row = self._fetch(file_id)
        if row is None:
            return None
        return SearchResult(
            file_id=file_id,
            path=row["path"],
            filename=row["filename"],
            duration=float(row["duration"] or 0.0),
            score=float(score),
            source=source,
            tags=db.list_tags(self.conn, file_id),
        )

    # -- 语义检索 ----------------------------------------------------------

    def search_text(self, query: str, limit: int = 20) -> list[SearchResult]:
        """文本语义检索（中文查询自动走翻译桥）。"""
        vec = self.embedder.embed_text(self._prepare_query(query))
        return self._search_vector(vec, limit, source="semantic")

    def search_similar(self, audio_path: str | Path, limit: int = 20) -> list[SearchResult]:
        """以声搜声。"""
        wav = load_for_embedding(audio_path)
        vec = self.embedder.embed_audio(wav)
        return self._search_vector(vec, limit, source="semantic")

    def _search_vector(self, vec: np.ndarray, limit: int, source: str) -> list[SearchResult]:
        if len(self.index) == 0:
            return []
        # 多取一些，过滤掉已从 SQLite 消失的悬挂 id
        ids, scores = self.index.search(vec, min(limit * 2, len(self.index)))
        results: list[SearchResult] = []
        for fid, sc in zip(ids, scores):
            if fid < 0:
                continue
            r = self._to_result(int(fid), float(sc), source)
            if r is not None:
                results.append(r)
            if len(results) >= limit:
                break
        return results

    # -- 关键词检索 --------------------------------------------------------

    def search_keyword(self, query: str, limit: int = 20) -> list[SearchResult]:
        """FTS5 关键词检索（文件名 / 路径 / 标签）。"""
        fts_query = self._build_fts_query(query)
        if not fts_query:
            return []
        rows = self.conn.execute(
            """SELECT rowid AS id, bm25(files_fts) AS rank
               FROM files_fts WHERE files_fts MATCH ?
               ORDER BY rank LIMIT ?""",
            (fts_query, limit),
        ).fetchall()
        results: list[SearchResult] = []
        for row in rows:
            # bm25 越小越相关，取负号转成"越大越好"
            r = self._to_result(int(row["id"]), -float(row["rank"]), "keyword")
            if r is not None:
                results.append(r)
        return results

    @staticmethod
    def _build_fts_query(query: str) -> str:
        """把用户输入转成安全的 FTS5 短语查询（加引号，转义内部引号）。"""
        cleaned = query.strip().replace('"', " ")
        if not cleaned:
            return ""
        # 用空格分隔的多个词做隐式 AND 短语匹配
        return f'"{cleaned}"'

    # -- 混合检索 ----------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        mode: str = "hybrid",
        limit: int = 20,
        semantic_weight: float = 0.8,
    ) -> list[SearchResult]:
        """统一入口。

        Args:
            mode: ``"semantic"`` | ``"keyword"`` | ``"hybrid"``
            semantic_weight: 混合模式下语义分权重（0~1）。
        """
        if mode == "semantic":
            return self.search_text(query, limit)
        if mode == "keyword":
            return self.search_keyword(query, limit)
        if mode != "hybrid":
            raise ValueError(f"未知检索模式：{mode}")

        sem = self.search_text(query, limit * 3)
        kw = self.search_keyword(query, limit * 3)

        scores: dict[int, float] = {}
        results: dict[int, SearchResult] = {}

        if sem:
            arr = np.array([r.score for r in sem], dtype=np.float32)
            norm = _normalize(arr)
            for r, s in zip(sem, norm):
                scores[r.file_id] = scores.get(r.file_id, 0.0) + semantic_weight * float(s)
                results[r.file_id] = r
        if kw:
            arr = np.array([r.score for r in kw], dtype=np.float32)
            norm = _normalize(arr)
            for r, s in zip(kw, norm):
                scores[r.file_id] = scores.get(r.file_id, 0.0) + (1 - semantic_weight) * float(s)
                if r.file_id not in results:
                    results[r.file_id] = r

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        out: list[SearchResult] = []
        for fid, sc in ranked:
            r = results[fid]
            r.score = sc
            r.source = "hybrid"
            out.append(r)
        return out
