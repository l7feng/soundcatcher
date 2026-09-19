"""CLAP 音频特征抽取 —— 纯 numpy 复刻 transformers ``ClapFeatureExtractor``。

为什么不用 transformers 的 ``ClapFeatureExtractor``：transformers 5.x 给它加了 PyTorch
硬依赖（``@requires(backends=("torch",))``），而我们的运行时只需要特征抽取，引入 torch
会带来数百 MB 依赖与打包负担。这里按 transformers ``audio_utils.py`` 的算法精确复刻，
纯 numpy 实现，与前缀 ONNX 导出的预处理保持一致。

对齐对象：``laion/clap-htsat-unfused``（经 Xenova ONNX 导出），预处理参数取自
``models/preprocessor_config.json``：

- 采样率 48 kHz，单声道
- ``truncation="rand_trunc"`` + ``padding="repeatpad"``，窗口 10 秒（480000 样本）
- slaney mel filterbank：``fmin=50``、``fmax=14000``、``n_mels=64``
- ``n_fft=1024``、``hop_length=480``、``center=True``（reflect 填充）、周期 Hann 窗
- ``power=2.0`` → ``log_mel="dB"``（``reference=1.0``、``min_value=1e-10``）
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# ---------------------------------------------------------------------------
# mel 频率刻度（与 transformers.audio_utils 一致）
# ---------------------------------------------------------------------------


def hertz_to_mel(freq: float | np.ndarray, mel_scale: str = "htk") -> float | np.ndarray:
    """频率（Hz）→ mel。支持 htk / slaney / kaldi 三种刻度。"""
    if mel_scale not in ("slaney", "htk", "kaldi"):
        raise ValueError('mel_scale 必须是 "htk"、"slaney" 或 "kaldi"')
    if mel_scale == "htk":
        return 2595.0 * np.log10(1.0 + (freq / 700.0))
    if mel_scale == "kaldi":
        return 1127.0 * np.log(1.0 + (freq / 700.0))

    # slaney：1 kHz 以下线性、以上对数
    min_log_hertz, min_log_mel = 1000.0, 15.0
    logstep = 27.0 / np.log(6.4)
    mels = 3.0 * freq / 200.0
    if isinstance(freq, np.ndarray):
        mels = mels.copy()
        log_region = freq >= min_log_hertz
        mels[log_region] = min_log_mel + np.log(freq[log_region] / min_log_hertz) * logstep
    elif freq >= min_log_hertz:
        mels = min_log_mel + np.log(freq / min_log_hertz) * logstep
    return mels


def mel_to_hertz(mels: float | np.ndarray, mel_scale: str = "htk") -> float | np.ndarray:
    """mel → 频率（Hz）。"""
    if mel_scale not in ("slaney", "htk", "kaldi"):
        raise ValueError('mel_scale 必须是 "htk"、"slaney" 或 "kaldi"')
    if mel_scale == "htk":
        return 700.0 * (np.power(10, mels / 2595.0) - 1.0)
    if mel_scale == "kaldi":
        return 700.0 * (np.exp(mels / 1127.0) - 1.0)

    min_log_hertz, min_log_mel = 1000.0, 15.0
    logstep = np.log(6.4) / 27.0
    freq = 200.0 * mels / 3.0
    if isinstance(mels, np.ndarray):
        freq = freq.copy()
        log_region = mels >= min_log_mel
        freq[log_region] = min_log_hertz * np.exp(logstep * (mels[log_region] - min_log_mel))
    elif mels >= min_log_mel:
        freq = min_log_hertz * np.exp(logstep * (mels - min_log_mel))
    return freq


def _triangular_filter_bank(fft_freqs: np.ndarray, filter_freqs: np.ndarray) -> np.ndarray:
    """三角滤波器组，形状 ``(num_frequency_bins, num_mel_filters)``。"""
    filter_diff = np.diff(filter_freqs)
    slopes = np.expand_dims(filter_freqs, 0) - np.expand_dims(fft_freqs, 1)
    down_slopes = -slopes[:, :-2] / filter_diff[:-1]
    up_slopes = slopes[:, 2:] / filter_diff[1:]
    return np.maximum(np.zeros(1), np.minimum(down_slopes, up_slopes))


def mel_filter_bank(
    num_frequency_bins: int,
    num_mel_filters: int,
    min_frequency: float,
    max_frequency: float,
    sampling_rate: int,
    norm: str | None = None,
    mel_scale: str = "htk",
) -> np.ndarray:
    """mel 滤波器组，形状 ``(num_frequency_bins, num_mel_filters)``。"""
    if norm is not None and norm != "slaney":
        raise ValueError('norm 必须是 None 或 "slaney"')

    mel_min = hertz_to_mel(min_frequency, mel_scale=mel_scale)
    mel_max = hertz_to_mel(max_frequency, mel_scale=mel_scale)
    mel_freqs = np.linspace(mel_min, mel_max, num_mel_filters + 2)
    filter_freqs = mel_to_hertz(mel_freqs, mel_scale=mel_scale)

    fft_freqs = np.linspace(0, sampling_rate // 2, num_frequency_bins)
    mel_filters = _triangular_filter_bank(fft_freqs, filter_freqs)

    if norm == "slaney":
        enorm = 2.0 / (filter_freqs[2 : num_mel_filters + 2] - filter_freqs[:num_mel_filters])
        mel_filters = mel_filters * np.expand_dims(enorm, 0)

    return mel_filters


def window_function(window_length: int, name: str = "hann", periodic: bool = True) -> np.ndarray:
    """窗函数，默认周期 Hann。"""
    length = window_length + 1 if periodic else window_length
    if name == "hann":
        window = np.hanning(length)
    elif name == "hamming":
        window = np.hamming(length)
    elif name == "boxcar":
        window = np.ones(length)
    elif name == "povey":
        window = np.power(np.hanning(length), 0.85)
    else:
        raise ValueError(f"未知窗函数 {name!r}")
    return window[:-1] if periodic else window


def power_to_db(
    spectrogram: np.ndarray,
    reference: float = 1.0,
    min_value: float = 1e-10,
    db_range: float | None = None,
) -> np.ndarray:
    """功率谱 → dB（``10*log10(x/reference)``，含下限裁剪）。"""
    reference = max(min_value, reference)
    spectrogram = np.clip(spectrogram, a_min=min_value, a_max=None)
    spectrogram = 10.0 * (np.log10(spectrogram) - np.log10(reference))
    if db_range is not None:
        spectrogram = np.clip(spectrogram, a_min=spectrogram.max() - db_range, a_max=None)
    return spectrogram


# ---------------------------------------------------------------------------
# CLAP 特征抽取器
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClapPreprocessConfig:
    """预处理参数（对齐 models/preprocessor_config.json）。"""

    sampling_rate: int = 48_000
    n_fft: int = 1024
    hop_length: int = 480
    feature_size: int = 64
    frequency_min: float = 50.0
    frequency_max: float = 14_000.0
    max_length_s: int = 10
    padding: str = "repeatpad"  # repeatpad | repeat | pad
    truncation: str = "rand_trunc"  # rand_trunc | fusion
    mel_floor: float = 1e-10

    @property
    def num_frequency_bins(self) -> int:
        return (self.n_fft >> 1) + 1

    @property
    def max_samples(self) -> int:
        return self.max_length_s * self.sampling_rate


class ClapFeatureExtractor:
    """复刻 transformers ``ClapFeatureExtractor``（rand_trunc + slaney 分支）。

    输入 48 kHz 单声道波形，输出形状 ``(1, n_frames, 64)`` 的 log-mel 特征，
    可直接喂给 ``onnx_audio_model.onnx``。
    """

    def __init__(self, cfg: ClapPreprocessConfig | None = None, *, seed: int | None = None):
        self.cfg = cfg or ClapPreprocessConfig()
        self.rng = np.random.default_rng(seed)
        self.window = window_function(self.cfg.n_fft, "hann", periodic=True)
        # rand_trunc 分支使用 slaney 滤波器组
        self.mel_filters = mel_filter_bank(
            num_frequency_bins=self.cfg.num_frequency_bins,
            num_mel_filters=self.cfg.feature_size,
            min_frequency=self.cfg.frequency_min,
            max_frequency=self.cfg.frequency_max,
            sampling_rate=self.cfg.sampling_rate,
            norm="slaney",
            mel_scale="slaney",
        )

    # -- 内部：向量化 STFT + mel + dB --------------------------------------

    def _stft_power(self, waveform: np.ndarray) -> np.ndarray:
        """功率谱，形状 ``(n_frames, num_frequency_bins)``。"""
        n_fft, hop = self.cfg.n_fft, self.cfg.hop_length
        if waveform.ndim != 1:
            raise ValueError(f"波形必须是一维，当前形状 {waveform.shape}")

        padded = np.pad(waveform, (n_fft // 2, n_fft // 2), mode="reflect")
        n_frames = 1 + (padded.size - n_fft) // hop
        frame_idx = np.arange(n_fft)[None, :] + hop * np.arange(n_frames)[:, None]
        frames = padded[frame_idx] * self.window[None, :]
        spec = np.fft.rfft(frames, n=n_fft, axis=1)
        return (np.abs(spec) ** 2.0).astype(np.float64)

    def _logmel(self, waveform: np.ndarray) -> np.ndarray:
        """log-mel（dB），形状 ``(n_frames, 64)``。"""
        power = self._stft_power(waveform.astype(np.float64))
        mel = np.dot(power, self.mel_filters)  # (n_frames, n_mels)
        mel = np.maximum(self.cfg.mel_floor, mel)
        return power_to_db(mel, reference=1.0, min_value=self.cfg.mel_floor)

    # -- 内部：截断/补齐 ---------------------------------------------------

    def _truncate_or_pad(self, waveform: np.ndarray) -> np.ndarray:
        max_len = self.cfg.max_samples

        if waveform.size > max_len:
            if self.cfg.truncation == "rand_trunc":
                overflow = waveform.size - max_len
                idx = int(self.rng.integers(0, overflow + 1))
                return waveform[idx : idx + max_len]
            raise NotImplementedError(f"暂不支持 truncation={self.cfg.truncation!r}")

        if waveform.size < max_len:
            n = waveform.size
            if n == 0:
                return np.zeros(max_len, dtype=np.float64)
            if self.cfg.padding == "repeatpad":
                n_repeat = int(max_len / n)
                waveform = np.tile(waveform, n_repeat)
            elif self.cfg.padding == "repeat":
                n_repeat = int(max_len / n)
                return np.tile(waveform, n_repeat + 1)[:max_len]
            elif self.cfg.padding != "pad":
                raise ValueError(f"未知 padding={self.cfg.padding!r}")
            waveform = np.pad(
                waveform, (0, max_len - waveform.size), mode="constant", constant_values=0.0
            )
        return waveform

    # -- 公开接口 ----------------------------------------------------------

    def __call__(self, waveform: np.ndarray, sampling_rate: int | None = None) -> np.ndarray:
        """提取特征。

        Args:
            waveform: 一维 float 波形（单声道）。
            sampling_rate: 必须等于配置采样率（不做隐式重采样，调用方负责）。

        Returns:
            形状 ``(1, n_frames, 64)`` 的 float32 特征。
        """
        if sampling_rate is not None and sampling_rate != self.cfg.sampling_rate:
            raise ValueError(
                f"采样率不匹配：期望 {self.cfg.sampling_rate}，收到 {sampling_rate}。"
                "请在解码阶段重采样到 48 kHz。"
            )

        waveform = np.asarray(waveform, dtype=np.float64).reshape(-1)
        prepared = self._truncate_or_pad(waveform)
        logmel = self._logmel(prepared)  # (n_frames, 64)
        return logmel[None, :].astype(np.float32)
