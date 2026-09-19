"""查询延迟粗测 + 外推（1.15 降级闭环，**只读**，可与扫描进程并发）。

对当前索引库跑若干次 search / similar，统计 P50/P95/mean 耗时，再按
faiss FlatIP（O(n) 精确检索）线性外推到 10 万级规模，供决策：
GUI 是否需要近似索引 / 后台队列。

用法::

    python scripts/bench_search.py            # 默认真实库 + 15 轮
    SOUNDCATCHER_DATA_HOME=<测试库> python scripts/bench_search.py --n 6
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from soundcatcher.config import Config  # noqa: E402
from soundcatcher.embedder import ClapEmbedder  # noqa: E402
from soundcatcher.indexer import VectorIndex  # noqa: E402
from soundcatcher.search import Searcher  # noqa: E402
from soundcatcher.gui.backend import _connect_readonly, _data_home  # noqa: E402

EN_QUERIES = [
    "glass breaking",
    "rain storm ambience",
    "heavy metal door slam",
    "bird singing morning",
    "engine rumble low",
    "footsteps on gravel",
]
ZH_QUERIES = [
    "玻璃破碎的声音",
    "沉重的金属门关闭声",
]
REF_AUDIO = Path(r"C:\Windows\Media\Windows Recycle.wav")


def _p(seq: list[float], pct: float) -> float:
    s = sorted(seq)
    if not s:
        return 0.0
    return s[min(len(s) - 1, int(len(s) * pct))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1, help="每组查询重复轮数")
    args = ap.parse_args()

    home = _data_home()
    cfg = Config.default()
    conn = _connect_readonly(home / "library.db")
    index = VectorIndex(home / "index" / "vectors.faiss")
    embedder = ClapEmbedder(cfg.models_dir)
    searcher = Searcher(
        conn, index, embedder,
        translator_factory=(lambda: __import__("soundcatcher.translator", fromlist=["OpusTranslator"]).OpusTranslator(cfg.translator_dir))
        if (cfg.translator_dir / "onnx_encoder_model.onnx").exists() else None,
    )
    n_total = len(index)
    print(f"库规模：{n_total} 条向量（SQLite 另行统计）")
    if n_total == 0:
        print("空库，跳过。")
        return 1

    # 预热（模型/页缓存）
    searcher.search("warmup", mode="semantic", limit=50)

    lat: dict[str, list[float]] = {"semantic-en": [], "semantic-zh": [], "similar": []}

    for _ in range(args.n):
        for q in EN_QUERIES:
            t0 = time.perf_counter()
            r = searcher.search(q, mode="semantic", limit=50)
            lat["semantic-en"].append(time.perf_counter() - t0)
            assert r
        for q in ZH_QUERIES:
            t0 = time.perf_counter()
            r = searcher.search(q, mode="semantic", limit=50)
            lat["semantic-zh"].append(time.perf_counter() - t0)
            assert r
        t0 = time.perf_counter()
        r = searcher.search_similar(REF_AUDIO, limit=50)
        lat["similar"].append(time.perf_counter() - t0)
        assert r

    # 全量外推目标（真实 10 万级）
    TARGET = 108_430
    scale = TARGET / max(1, n_total)

    print(f"\n{'模式':<14}{'轮次':<6}{'P50':>10}{'P95':>10}{'均值':>10}{'外推P95':>12}")
    print("-" * 66)
    for name, arr in lat.items():
        if not arr:
            continue
        ms = lambda s: s * 1000  # noqa: E731
        p50 = _p(arr, 0.50)
        p95 = _p(arr, 0.95)
        avg = statistics.mean(arr)
        print(
            f"{name:<14}{len(arr):<6}{ms(p50):>9.2f}ms{ms(p95):>9.2f}ms{ms(avg):>9.2f}ms"
            f"{ms(p95) * scale:>10.2f}ms"
        )

    # 检索侧外推：只统计纯检索模式（en / similar），不含翻译桥常数
    search_arrs = [lat[k] for k in ("semantic-en", "similar")]
    p95_total = max(ms(_p(arr, 0.95)) * scale for arr in search_arrs if arr)
    verdict = "亚秒达标" if p95_total < 1000 else "超 1 秒，需评估近似索引"
    zh_total = ms(_p(lat["semantic-zh"], 0.95)) * scale if lat.get("semantic-zh") else 0.0
    zh_verdict = "达标（≤3s）" if zh_total < 3000 else "超时"
    print(f"\n检索侧外推（{TARGET} 条，en/similar 最坏 P95）≈ {p95_total:.0f} ms → {verdict}（纯检索，不含翻译常数）")
    print(f"中文（含翻译桥 0.5~0.9s 常数，仅与查询数有关不与库规模线性相关）外推 ≈ {zh_total:.0f} ms → 验收 {zh_verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())