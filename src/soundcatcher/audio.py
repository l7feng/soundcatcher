"""音频 I/O —— 基于 PyAV（ffmpeg 绑定）的探测与解码。

设计目标：
- **全格式**：WAV / AIFF / RF64 / FLAC / MP3 / M4A / OGG / OPUS / CAF 等一律经 ffmpeg 解码
- **统一口径**：所有音频重采样为 48 kHz 单声道 float32（CLAP 要求的输入规格）
- **确定性**：长音频取中段窗口而非随机裁剪，保证同一文件多次索引结果一致

代表性窗口策略（阶段 1）：整段 ≤ 10 秒直接用；超过 10 秒取中段 10 秒。后续可升级为
多窗口特征平均以提升长环境音的代表性。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np

logger = logging.getLogger(__name__)

TARGET_RATE = 48_000
WINDOW_SAMPLES = TARGET_RATE * 10  # CLAP 的 10 秒窗口


@dataclass(frozen=True)
class AudioInfo:
    """音频文件的基础元数据。"""

    duration: float
    sample_rate: int
    channels: int
    codec: str
    format: str


def probe(path: str | Path) -> AudioInfo:
    """探测音频元数据（不解码全部内容）。"""
    with av.open(str(path), metadata_errors="ignore") as container:
        if not container.streams.audio:
            raise ValueError(f"文件不含音频流：{path}")
        stream = container.streams.audio[0]
        duration = 0.0
        if stream.duration is not None:
            duration = float(stream.duration * stream.time_base)
        elif container.duration is not None:
            duration = float(container.duration / av.time_base)
        return AudioInfo(
            duration=duration,
            sample_rate=int(stream.codec_context.sample_rate or 0),
            channels=int(stream.codec_context.channels or 0),
            codec=stream.codec_context.name,
            format=container.format.name.split(",")[0],
        )


def decode_mono48k(path: str | Path, *, max_seconds: float | None = None) -> np.ndarray:
    """解码为 48 kHz 单声道 float32 波形。

    Args:
        path: 音频文件路径。
        max_seconds: 最多解码的秒数（从开头计），用于为大文件兜底。``None`` 表示全部解码。

    Returns:
        一维 float32 数组，取值约在 [-1, 1]。
    """
    limit = None if max_seconds is None else int(max_seconds * TARGET_RATE)
    parts: list[np.ndarray] = []

    with av.open(str(path), metadata_errors="ignore") as container:
        if not container.streams.audio:
            raise ValueError(f"文件不含音频流：{path}")
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="flt", layout="mono", rate=TARGET_RATE)
        total = 0
        finished = True
        for frame in container.decode(stream):
            for rframe in resampler.resample(frame):
                arr = rframe.to_ndarray().reshape(-1).astype(np.float32)
                parts.append(arr)
                total += arr.size
            if limit is not None and total >= limit:
                finished = False
                break
        if finished:
            # 冲刷重采样器尾部样本
            for rframe in resampler.resample(None):
                parts.append(rframe.to_ndarray().reshape(-1).astype(np.float32))

    if not parts:
        return np.zeros(0, dtype=np.float32)

    wav = np.concatenate(parts)
    if limit is not None:
        wav = wav[:limit]
    return wav


def representative_window(wav: np.ndarray, window: int = WINDOW_SAMPLES) -> np.ndarray:
    """取代表性窗口：≤ window 直接用，超出取中段（确定性）。"""
    if wav.size <= window:
        return wav
    start = (wav.size - window) // 2
    return wav[start : start + window]


def load_for_embedding(path: str | Path) -> np.ndarray:
    """便捷入口：解码 + 取代表性窗口，得到可直接嵌入的波形。

    对大文件先限制解码 60 秒，避免一次性读入超长环境音造成内存压力。
    """
    wav = decode_mono48k(path, max_seconds=60.0)
    return representative_window(wav)
