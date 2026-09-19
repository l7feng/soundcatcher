"""探测 ONNX 音频塔期望的张量布局。

transformers 的 ClapFeatureExtractor 产出 ``(1, n_frames, 64)``，但 ONNX 签名是 4 维
``(batch, num_channels, height, width)``。需要确认 height/width 对应 time 还是 mel。

方法：合成低/中/高频三段音频，用语义文本做交叉验证，看哪种布局给出更合理的匹配。
"""

from pathlib import Path
import sys

import numpy as np
import onnxruntime as ort

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from soundcatcher.features import ClapFeatureExtractor  # noqa: E402

MODELS = Path(__file__).resolve().parent.parent / "models"
SR = 48_000


def tone(freq: float, seconds: float = 3.0, kind: str = "sine") -> np.ndarray:
    t = np.linspace(0, seconds, int(SR * seconds), endpoint=False, dtype=np.float64)
    if kind == "sine":
        wav = 0.6 * np.sin(2 * np.pi * freq * t)
    else:  # noise 带通近似：白噪 + 简单低通/高通
        wav = 0.3 * np.random.default_rng(0).standard_normal(t.size)
    return wav.astype(np.float64)


def main() -> None:
    fe = ClapFeatureExtractor(seed=0)
    audio_sess = ort.InferenceSession(str(MODELS / "onnx_audio_model.onnx"),
                                      providers=["CPUExecutionProvider"])
    text_sess = ort.InferenceSession(str(MODELS / "onnx_text_model.onnx"),
                                     providers=["CPUExecutionProvider"])

    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(str(MODELS / "tokenizer.json"))

    # 三段测试音：低频轰鸣 / 中频哨音 / 高频尖啸
    clips = {
        "bass_80hz": tone(80),
        "mid_1khz": tone(1000),
        "high_8khz": tone(8000),
    }
    texts = [
        "a deep low rumbling bass sound",
        "a mid pitched whistle tone",
        "a very high pitched sharp squeal",
    ]

    # 文本嵌入
    ids = [tok.encode(t).ids for t in texts]
    maxlen = max(len(x) for x in ids)
    batch = np.ones((len(ids), maxlen), dtype=np.int64)
    for i, row in enumerate(ids):
        batch[i, : len(row)] = row
    temb = text_sess.run(None, {"input_ids": batch})[0]
    temb /= np.linalg.norm(temb, axis=1, keepdims=True)

    for layout in ("time_major", "mel_major"):
        print(f"\n===== 布局: {layout} =====")
        aembs = []
        for name, wav in clips.items():
            feats = fe(wav, sampling_rate=SR)  # (1, frames, 64)
            if layout == "time_major":
                x = feats[:, None, :, :]      # (1, 1, frames, 64)
            else:
                x = feats[:, None, :, :].transpose(0, 1, 3, 2)  # (1, 1, 64, frames)
            emb = audio_sess.run(None, {"input_features": x.astype(np.float32)})[0]
            aembs.append(emb[0] / np.linalg.norm(emb[0]))
        A = np.stack(aembs)
        sim = A @ temb.T
        print("            " + "  ".join(f"{t[:14]:>14}" for t in
                                          ["low bass", "mid whistle", "high squeal"]))
        for i, name in enumerate(clips):
            print(f"{name:>11} " + "  ".join(f"{sim[i, j]:>14.4f}" for j in range(len(texts))))
        # 对角占优得分：正确布局应让每个音频最匹配对应文本
        diag = sum(1 for i in range(len(clips)) if int(np.argmax(sim[i])) == i)
        print(f"对角命中: {diag}/3")


if __name__ == "__main__":
    main()
