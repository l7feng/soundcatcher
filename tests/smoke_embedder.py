"""ClapEmbedder 端到端冒烟测试（合成音 + 语义文本）。

验证：
1. 音频/文本两塔均输出 512 维归一化嵌入
2. 语义匹配方向合理（低频音 ↔ "low bass" 等）
3. 批量接口与单条接口一致
"""

from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from soundcatcher.embedder import ClapEmbedder  # noqa: E402

SR = 48_000


def tone(freq: float, seconds: float = 4.0) -> np.ndarray:
    t = np.linspace(0, seconds, int(SR * seconds), endpoint=False)
    return (0.6 * np.sin(2 * np.pi * freq * t)).astype(np.float64)


def main() -> None:
    emb = ClapEmbedder(ROOT / "models", seed=0)

    clips = {
        "bass_80hz": tone(80),
        "mid_1khz": tone(1000),
        "high_6khz": tone(6000),
    }
    texts = [
        "a deep low rumbling bass sound",
        "a mid pitched tone",
        "a high pitched whistle",
    ]

    for name, wav in clips.items():
        v = emb.embed_audio(wav, sampling_rate=SR)
        print(f"[audio] {name:>10} shape={v.shape} norm={np.linalg.norm(v):.4f}")

    t = emb.embed_texts(texts)
    print(f"[text ] embeds shape={t.shape} norms={np.linalg.norm(t, axis=1).round(4)}")

    sims = np.stack([emb.embed_audio(w, sampling_rate=SR) for w in clips.values()]) @ t.T
    print("\n相似度矩阵（行=音频，列=文本）：")
    header = "".join(f"{x[:18]:>20}" for x in texts)
    print(f"{'':>12}{header}")
    for i, name in enumerate(clips):
        row = "".join(f"{sims[i, j]:>20.4f}" for j in range(len(texts)))
        print(f"{name:>12}{row}")

    hit = sum(int(np.argmax(sims[i])) == i for i in range(len(clips)))
    print(f"\n对角命中: {hit}/3")

    # 批量一致性
    batch = emb.embed_audio_batch(list(clips.values()), sampling_rate=SR)
    single = np.stack([emb.embed_audio(w, sampling_rate=SR) for w in clips.values()])
    print(f"批量 vs 单条最大差异: {np.abs(batch - single).max():.2e}")


if __name__ == "__main__":
    main()
