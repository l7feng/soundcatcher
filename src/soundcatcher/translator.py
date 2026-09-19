"""离线中→英翻译桥（OPUS-MT，ONNX + HuggingFace tokenizers）。

CLAP 的文本塔是英文 RoBERTa，中文查询基本会退化成 ``<unk>`` 串。这个模块把中文
查询翻成英文后再交给 CLAP 编码，让中文检索可用——全程离线，不依赖任何在线服务。

模型：``Helsinki-NLP/opus-mt-zh-en``（经 Xenova ONNX 导出）
- encoder：``input_ids`` + ``attention_mask`` → ``last_hidden_state``
- decoder：merged 版（KV cache 合并，``use_cache_branch`` 切换首步/增量）
- 词表：仓库自带的 ``tokenizer.json``（Marian Unigram，65001 词，``</s>``=0、
  ``<pad>``=65000）。**不要**改用独立的 ``source.spm``/``target.spm``——那是另一套
  32000 词表，与模型的 65001 输出维度对不上，会解出乱码。

解码策略：贪心（够快够用）。模型自带 beam=6 的配置，但查询翻译是短文本，
贪心在 CPU 上的延迟更低，质量差异对"关键词级"查询可忽略。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

logger = logging.getLogger(__name__)

ENCODER = "onnx_encoder_model.onnx"
DECODER = "onnx_decoder_model_merged.onnx"
TOKENIZER = "tokenizer.json"

EOS_ID = 0
DECODER_START_ID = 65000
NUM_LAYERS = 6
NUM_HEADS = 8
HEAD_DIM = 64


def has_cjk(text: str) -> bool:
    """文本是否含中日韩字符。"""
    return any("\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf" for ch in text)


class OpusTranslator:
    """离线中→英翻译器。"""

    def __init__(self, models_dir: str | Path, *, provider: str = "CPUExecutionProvider"):
        self.dir = Path(models_dir)
        self.tokenizer = self._load_tokenizer()
        self.tokenizer.no_padding()
        self.tokenizer.no_truncation()
        self.encoder = ort.InferenceSession(str(self.dir / ENCODER), providers=[provider])
        self.decoder = ort.InferenceSession(str(self.dir / DECODER), providers=[provider])
        self._decoder_out_names = [o.name for o in self.decoder.get_outputs()]
        logger.info("OPUS-MT 翻译器就绪")

    def translate(self, text: str, *, max_new_tokens: int = 128) -> str:
        """中文（或任意源语言）→ 英文。"""
        text = text.strip()
        if not text:
            return ""

        enc = self.tokenizer.encode(text)  # post_processor 已在末尾追加 </s>
        input_ids = np.asarray([enc.ids], dtype=np.int64)
        attention_mask = np.asarray([enc.attention_mask], dtype=np.int64)

        enc_out = self.encoder.run(
            None, {"input_ids": input_ids, "attention_mask": attention_mask}
        )[0]

        past = self._empty_past()
        enc_past: dict[str, np.ndarray] | None = None
        decoder_ids = np.asarray([[DECODER_START_ID]], dtype=np.int64)
        use_cache = np.asarray([False])
        generated: list[int] = []

        for _ in range(max_new_tokens):
            feeds = {
                "input_ids": decoder_ids,
                "encoder_hidden_states": enc_out,
                "encoder_attention_mask": attention_mask,
                "use_cache_branch": use_cache,
                **past,
            }
            outputs = self.decoder.run(None, feeds)
            next_id = int(np.argmax(outputs[0][0, -1, :]))
            if next_id == EOS_ID:
                break
            generated.append(next_id)

            # 增量步返回的 encoder present 是零长度占位（编码器 KV 只在第 0 步算一次），
            # 因此 encoder 侧固定用第 0 步的输出，只滚动更新 decoder 侧。
            present = dict(zip(self._decoder_out_names[1:], outputs[1:]))
            if enc_past is None:
                enc_past = {
                    k.replace("present.", "past_key_values."): v
                    for k, v in present.items()
                    if ".encoder." in k
                }
            past = {
                **{
                    k.replace("present.", "past_key_values."): v
                    for k, v in present.items()
                    if ".decoder." in k
                },
                **enc_past,
            }
            decoder_ids = np.asarray([[next_id]], dtype=np.int64)
            use_cache = np.asarray([True])

        return self.tokenizer.decode(generated, skip_special_tokens=True).strip()

    # -- 内部 --------------------------------------------------------------

    def _load_tokenizer(self) -> Tokenizer:
        """加载 ``tokenizer.json``。

        Xenova 导出的该文件里 normalizer 声明为 ``Precompiled`` 但
        ``precompiled_charsmap`` 是 null，Rust 端会直接 panic；这里把失效的 normalizer
        置空后再加载。丢掉的只是 NFKC 类字符归一化，对中文查询分词影响很小，换来的
        是"只有一个 ONNX 运行时依赖"。
        """
        data = json.loads((self.dir / TOKENIZER).read_text(encoding="utf-8"))
        norm = data.get("normalizer")
        if isinstance(norm, dict) and norm.get("precompiled_charsmap") is None:
            data["normalizer"] = None
            logger.debug("已移除 tokenizer.json 中失效的 Precompiled normalizer")
        return Tokenizer.from_str(json.dumps(data, ensure_ascii=False))

    def _empty_past(self) -> dict[str, np.ndarray]:
        # 首步（use_cache_branch=False）走"无缓存"分支，past 值被忽略，但形状必须合法：
        # 长度 0 会在 encoder_attn 的 Reshape 处报错，因此用长度 1 的占位张量。
        past: dict[str, np.ndarray] = {}
        for i in range(NUM_LAYERS):
            for side in ("decoder", "encoder"):
                past[f"past_key_values.{i}.{side}.key"] = np.zeros(
                    (1, NUM_HEADS, 1, HEAD_DIM), dtype=np.float32
                )
                past[f"past_key_values.{i}.{side}.value"] = np.zeros(
                    (1, NUM_HEADS, 1, HEAD_DIM), dtype=np.float32
                )
        return past
