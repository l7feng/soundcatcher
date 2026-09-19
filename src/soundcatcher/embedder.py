"""CLAP ONNX 双塔嵌入器。

加载 ``models/onnx_audio_model.onnx``（音频塔）与 ``models/onnx_text_model.onnx``
（文本塔），输出同一 512 维潜空间的 L2 归一化嵌入向量。

模型签名（实测）：

- 音频塔：``input_features`` ``(batch, 1, n_frames, 64)`` float32 → ``audio_embeds`` ``(batch, 512)``
- 文本塔：``input_ids`` ``(batch, seq)`` int64 → ``text_embeds`` ``(batch, 512)``

文本塔没有 ``attention_mask`` 输入，因此批量编码时需注意：本实现把长度相近的文本
分组并用 ``padding`` 补齐后编码，单条查询（主要场景）不产生任何补齐。
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from .features import ClapFeatureExtractor

logger = logging.getLogger(__name__)

AUDIO_MODEL = "onnx_audio_model.onnx"
TEXT_MODEL = "onnx_text_model.onnx"
TOKENIZER = "tokenizer.json"

# CLAP 文本端标准最大长度（RoBERTa 输入上限）
TEXT_MAX_LENGTH = 77


def _l2_normalize(x: np.ndarray) -> np.ndarray:
    """按最后一维做 L2 归一化（零向量安全）。"""
    norms = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.maximum(norms, 1e-12)


class ClapEmbedder:
    """CLAP 双塔 ONNX 嵌入器。

    Args:
        models_dir: 含 ONNX 模型与 tokenizer 的目录。
        provider: onnxruntime 执行提供程序，默认 CPU；GPU 可传 ``DmlExecutionProvider``。
        seed: 特征抽取器的随机种子（rand_trunc 裁剪用）；``None`` 表示每次随机。
    """

    def __init__(
        self,
        models_dir: str | Path,
        *,
        provider: str = "CPUExecutionProvider",
        seed: int | None = None,
    ):
        self.models_dir = Path(models_dir)
        self.provider = provider

        self.feature_extractor = ClapFeatureExtractor(seed=seed)
        self.tokenizer = Tokenizer.from_file(str(self.models_dir / TOKENIZER))
        self.tokenizer.enable_truncation(max_length=TEXT_MAX_LENGTH)

        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.audio_session = ort.InferenceSession(
            str(self.models_dir / AUDIO_MODEL), sess_options, providers=[provider]
        )
        self.text_session = ort.InferenceSession(
            str(self.models_dir / TEXT_MODEL), sess_options, providers=[provider]
        )
        self._audio_input = self.audio_session.get_inputs()[0].name
        self._text_input = self.text_session.get_inputs()[0].name
        logger.info("CLAP 双塔就绪（provider=%s）", provider)

    # -- 音频 --------------------------------------------------------------

    def embed_audio(self, waveform: np.ndarray, sampling_rate: int = 48_000) -> np.ndarray:
        """单段音频 → 512 维归一化嵌入。"""
        features = self.feature_extractor(waveform, sampling_rate=sampling_rate)  # (1, T, 64)
        features = features[:, None, :, :]  # (1, 1, T, 64) —— ONNX 期望 (batch, ch, time, mel)
        embeds = self.audio_session.run(None, {self._audio_input: features})[0]
        return _l2_normalize(np.asarray(embeds, dtype=np.float32))[0]

    def embed_audio_batch(
        self, waveforms: list[np.ndarray], sampling_rate: int = 48_000
    ) -> np.ndarray:
        """多段音频 → ``(N, 512)`` 归一化嵌入。"""
        if not waveforms:
            return np.zeros((0, 512), dtype=np.float32)
        feats = np.concatenate(
            [self.feature_extractor(w, sampling_rate=sampling_rate) for w in waveforms], axis=0
        )
        feats = feats[:, None, :, :]  # (N, 1, T, 64)
        embeds = self.audio_session.run(None, {self._audio_input: feats})[0]
        return _l2_normalize(np.asarray(embeds, dtype=np.float32))

    # -- 文本 --------------------------------------------------------------

    def embed_text(self, text: str) -> np.ndarray:
        """单条文本 → 512 维归一化嵌入。"""
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """多条文本 → ``(N, 512)`` 归一化嵌入。

        文本塔无 attention_mask，故按长度分桶、桶内补齐，减少 padding 对注意力的干扰。
        """
        if not texts:
            return np.zeros((0, 512), dtype=np.float32)

        encodings = [self.tokenizer.encode(t).ids for t in texts]
        order = sorted(range(len(encodings)), key=lambda i: len(encodings[i]))
        embeds = np.zeros((len(texts), 512), dtype=np.float32)

        bucket: list[int] = []
        bucket_len = 0

        def flush() -> None:
            if not bucket:
                return
            max_len = max(len(encodings[i]) for i in bucket)
            pad_id = self.tokenizer.token_to_id("<pad>") or 1
            batch = np.full((len(bucket), max_len), pad_id, dtype=np.int64)
            for row, i in enumerate(bucket):
                batch[row, : len(encodings[i])] = encodings[i]
            out = self.text_session.run(None, {self._text_input: batch})[0]
            out = _l2_normalize(np.asarray(out, dtype=np.float32))
            for row, i in enumerate(bucket):
                embeds[i] = out[row]
            bucket.clear()

        for i in order:
            if bucket and len(encodings[i]) > bucket_len * 2:
                flush()
            bucket.append(i)
            bucket_len = len(encodings[i])
        flush()

        return embeds
