"""UCS 自动分类（753 类零样本，任务 1.14）。

思路：UCS 8.2.1 官方英文全表（753 个子分类，公共领域）每条构造 3 条文本提示词
（名称 / 解释 / 同义词），经 CLAP **文本塔**嵌入后取均值，得到 753×512 的原型矩阵
（``data/ucs/prototypes.npy``）。对库内任一音频，用 CLAP 音频塔的 512d 向量与全部
原型点积（均已 L2 归一化 → 余弦），取 top-k 即为分类结果 + 置信度。

中文侧：`catalog/ucs-zh-en.tsv` 的 285 条按 **CatID** 合并进官方表，提供分类结果的
中文显示名与中文同义词标签；未覆盖的条目用英文名兜底。

用法：
    soundcatcher ucs init            # 构建原型（需文本塔，一次性）
    soundcatcher ucs tag             # 对已嵌入的库文件分类并写 ucs_labels + 标签

生成物全部在 ``data/ucs/``（派生数据，可随时重建）；``catalog/`` 是静态语料。
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .embedder import ClapEmbedder

logger = logging.getLogger(__name__)

# 原型版本号：提示词模板或嵌入模型变更时必须递增（写入 meta，供 tag 命令校验）
PROTO_VERSION = 1
# 每类提示词变体数（名称/解释/同义词）
N_VARIANTS = 3
# 同义词变体最多取前 N 个（77 token 限制内）
SYN_LIMIT = 12
# 置信度 softmax 温度（余弦分数 ~0.1~0.6，温度取小值拉开差距）
SOFTMAX_TEMP = 0.05


@dataclass
class UcsEntry:
    """一条 UCS 子分类（官方英文 + 可选中文侧）。"""

    catid: str
    category: str
    subcategory: str
    catshort: str
    explanation: str
    synonyms: list[str] = field(default_factory=list)
    category_zh: str = ""
    subcategory_zh: str = ""
    synonyms_zh: list[str] = field(default_factory=list)

    @property
    def display_zh(self) -> str:
        """中文显示名（无中文时退回英文）。"""
        if self.category_zh or self.subcategory_zh:
            return f"{self.category_zh or self.category}/{self.subcategory_zh or self.subcategory}"
        return f"{self.category}/{self.subcategory}"

    @property
    def display_en(self) -> str:
        return f"{self.category}/{self.subcategory}"


class UcsCatalog:
    """加载官方英文全表并与中文 TSV 按 CatID 合并。"""

    def __init__(self, catalog_dir: str | Path):
        self.catalog_dir = Path(catalog_dir)
        self.entries: list[UcsEntry] = []
        self._load()

    def _load(self) -> None:
        csv_path = self.catalog_dir / "ucs_v8.2.1.csv"
        tsv_path = self.catalog_dir / "ucs-zh-en.tsv"
        if not csv_path.exists():
            raise FileNotFoundError(f"缺少 UCS 官方全表：{csv_path}")

        with open(csv_path, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))

        zh: dict[str, dict[str, str]] = {}
        if tsv_path.exists():
            with open(tsv_path, encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    if r.get("CatID"):
                        zh[r["CatID"].strip()] = r

        self.entries = []
        for r in rows:
            catid = r["CatID"].strip()
            syns = [s.strip() for s in r.get("Synonyms", "").split(",") if s.strip()]
            e = UcsEntry(
                catid=catid,
                category=r.get("Category", "").strip(),
                subcategory=r.get("SubCategory", "").strip(),
                catshort=r.get("CatShort", "").strip(),
                explanation=r.get("Explanations", "").strip(),
                synonyms=syns,
            )
            if catid in zh:
                zr = zh[catid]
                e.category_zh = (zr.get("Category_zh") or "").strip()
                e.subcategory_zh = (zr.get("SubCategory_zh") or "").strip()
                e.synonyms_zh = [
                    s.strip() for s in (zr.get("Synonyms_zh") or "").split("、") if s.strip()
                ]
            self.entries.append(e)

        n_zh = sum(1 for e in self.entries if e.category_zh or e.subcategory_zh)
        logger.info("UCS 目录加载：%d 条（含中文 %d 条）", len(self.entries), n_zh)

    def __len__(self) -> int:
        return len(self.entries)

    def __getitem__(self, i: int) -> UcsEntry:
        return self.entries[i]

    def catid_index(self) -> dict[str, int]:
        return {e.catid: i for i, e in enumerate(self.entries)}

    @classmethod
    def from_meta(cls, meta: dict) -> "UcsCatalog":
        """从 catalog.json 的 meta 重建目录（tag 阶段用，无需静态语料）。"""
        c = cls.__new__(cls)
        c.catalog_dir = Path("")
        c.entries = [
            UcsEntry(
                catid=m["catid"],
                category=m["category"],
                subcategory=m["subcategory"],
                catshort=m.get("catshort", ""),
                explanation="",
                category_zh=m.get("category_zh", ""),
                subcategory_zh=m.get("subcategory_zh", ""),
                synonyms_zh=m.get("synonyms_zh", []),
            )
            for m in meta["entries"]
        ]
        return c

    # -- 提示词 ------------------------------------------------------------

    @staticmethod
    def _prompts(e: UcsEntry) -> list[str]:
        """每类 3 条提示词变体：名称 / 解释 / 同义词（各自在 77 token 预算内）。"""
        head = f"{e.subcategory} {e.category}"
        variants = [f"sound of {head}"]  # 1 名称
        if e.explanation:  # 2 解释
            variants.append(f"{head}: {e.explanation}")
        if e.synonyms:  # 3 同义词
            variants.append(f"{head}, {', '.join(e.synonyms[:SYN_LIMIT])}")
        return variants

    # -- 原型构建与持久化 --------------------------------------------------

    def build_prototypes(self, embedder: ClapEmbedder, out_dir: str | Path) -> np.ndarray:
        """把 753 类 × 3 变体文本嵌入为 753×512 原型矩阵并落盘。

        返回 (N, 512)；同时写 ``catalog.json``（与矩阵行号一一对应）。
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        prompts: list[str] = []
        for e in self.entries:
            prompts.extend(self._prompts(e))

        embeds = embedder.embed_texts(prompts)  # (753*3, 512)，已是 L2 归一化
        matrix = embeds.reshape(len(self.entries), N_VARIANTS, -1).mean(axis=1)
        norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
        matrix = matrix / np.maximum(norms, 1e-12)

        np.save(out_dir / "prototypes.npy", matrix.astype(np.float32))
        meta = {
            "proto_version": PROTO_VERSION,
            "n_classes": len(self.entries),
            "dim": 512,
            "entries": [
                {
                    "catid": e.catid,
                    "category": e.category,
                    "subcategory": e.subcategory,
                    "catshort": e.catshort,
                    "category_zh": e.category_zh,
                    "subcategory_zh": e.subcategory_zh,
                    "synonyms_zh": e.synonyms_zh[:6],
                }
                for e in self.entries
            ],
        }
        with open(out_dir / "catalog.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        logger.info("原型已构建：%d 类 × 512d → %s", len(self.entries), out_dir)
        return matrix


class UcsClassifier:
    """加载原型并做零样本分类（纯 numpy，不依赖模型）。"""

    def __init__(self, catalog: UcsCatalog, prototypes: np.ndarray, *, top_k: int = 5,
                 temp: float = SOFTMAX_TEMP):
        if prototypes.shape != (len(catalog), 512):
            raise ValueError(
                f"原型形状 {(prototypes.shape)} 与目录条数 {len(catalog)}×512 不符"
            )
        self.catalog = catalog
        self.prototypes = prototypes.astype(np.float32)  # (C, 512)
        self.top_k = top_k
        self.temp = temp

    @classmethod
    def from_dir(cls, ucs_dir: str | Path, *, top_k: int = 5,
                 temp: float = SOFTMAX_TEMP) -> "UcsClassifier":
        ucs_dir = Path(ucs_dir)
        proto = np.load(ucs_dir / "prototypes.npy")
        with open(ucs_dir / "catalog.json", encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("proto_version") != PROTO_VERSION:
            raise ValueError(
                f"原型版本 {meta.get('proto_version')} ≠ 当前 {PROTO_VERSION}，请先运行 "
                "`soundcatcher ucs init` 重建"
            )
        catalog = UcsCatalog.from_meta(meta)
        return cls(catalog, proto, top_k=top_k, temp=temp)

    def classify_vectors(self, vecs: np.ndarray) -> list[list[tuple[UcsEntry, float, float]]]:
        """批量分类 ``(N, 512)`` 音频向量。

        返回 ``N`` 个列表，每个列表 ``top_k`` 项 ``(条目, 余弦分, 置信度)``。
        """
        vecs = np.asarray(vecs, dtype=np.float32)
        if vecs.ndim == 1:
            vecs = vecs[None, :]
        scores = vecs @ self.prototypes.T  # (N, C) 余弦
        order = np.argsort(-scores, axis=1)[:, : self.top_k]

        results: list[list[tuple[UcsEntry, float, float]]] = []
        for i in range(vecs.shape[0]):
            row = scores[i, order[i]]
            # top-k softmax（温度缩放后的相对置信度）
            z = np.exp((row - row.max()) / self.temp)
            conf = z / z.sum()
            results.append(
                [
                    (self.catalog[int(idx)], float(score), float(c))
                    for idx, score, c in zip(order[i], row, conf)
                ]
            )
        return results