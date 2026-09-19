"""阶段1 探测脚本：验证 CLAP ONNX 双塔 + 特征抽取器 + tokenizer 全链路。

不进入正式管线，仅用于确认：
1. transformers 5.x 的 ClapFeatureExtractor 能否生成 (1, 1, 64, 1000) 的 input_features
2. audio 塔 ONNX 输出 (1, 512)
3. text 塔 ONNX 输出 (1, 512)
4. 文本/音频在同一潜空间（用一段合成音频做粗验证）
"""

import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"


def probe_feature_extractor():
    from transformers import ClapFeatureExtractor

    fe = ClapFeatureExtractor.from_pretrained(str(MODELS))
    print(f"[FE] 采样率={fe.sampling_rate} mel_bins={fe.feature_size} "
          f"n_fft={fe.n_fft} hop={fe.hop_length} max_frames={fe.nb_max_frames}")

    # 造 1 秒 440Hz 正弦（48kHz），padding="repeatpad" 会补齐到 10 秒窗口
    sr = fe.sampling_rate
    t = np.linspace(0, 1.0, sr, endpoint=False, dtype=np.float32)
    audio = 0.5 * np.sin(2 * np.pi * 440.0 * t)

    inputs = fe(audio, sampling_rate=sr, return_tensors="np")
    feats = np.asarray(inputs["input_features"])
    print(f"[FE] input_features 形状 = {feats.shape}, dtype={feats.dtype}")
    return feats


def probe_audio_tower(feats):
    sess = ort.InferenceSession(str(MODELS / "onnx_audio_model.onnx"),
                                providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    out = sess.run(None, {name: feats.astype(np.float32)})[0]
    print(f"[audio] embeds 形状 = {out.shape}, 范数 = {np.linalg.norm(out):.3f}")
    return out


def probe_text_tower():
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(str(MODELS))
    texts = ["heavy metal door slam", "gentle rain on leaves"]
    enc = tok(texts, return_tensors="np", padding=True)
    print(f"[text] input_ids 形状 = {enc['input_ids'].shape}")
    sess = ort.InferenceSession(str(MODELS / "onnx_text_model.onnx"),
                                providers=["CPUExecutionProvider"])
    out = sess.run(None, {"input_ids": enc["input_ids"].astype(np.int64)})[0]
    print(f"[text] embeds 形状 = {out.shape}")
    return tok, out


if __name__ == "__main__":
    print(f"Python {sys.version.split()[0]}")
    feats = probe_feature_extractor()
    a = probe_audio_tower(feats)
    tok, t = probe_text_tower()
    # 粗验证：同空间可比较（用余弦相似度矩阵看一眼数值范围是否合理）
    if a.shape[1] == t.shape[1]:
        an = a / np.linalg.norm(a, axis=1, keepdims=True)
        tn = t / np.linalg.norm(t, axis=1, keepdims=True)
        sims = an @ tn.T
        print(f"[check] 正弦波 vs 文本余弦相似度 = {sims.ravel()}")
        print("探测完成：双塔 512 维共享空间可用")
