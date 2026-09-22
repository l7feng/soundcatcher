"""下载 CLAP 音频/文本 ONNX 模型与中英翻译模型。

来源（均经 HF 镜像）：

- ``Xenova/clap-htsat-unfused``      → ``<models>/``（音频塔 + 文本塔 + tokenizer）
- ``Xenova/opus-mt-zh-en``           → ``<models>/opus-mt-zh-en/``（中文查询翻译桥）

**落点由 ``soundcatcher.Config.models_dir`` 决定**（不再硬编码），优先级：
``SOUNDCATCHER_MODELS`` > 工程层 ``<工程>/models`` > 仓内 ``<仓>/models``。
现行布局下即仓内 ``<仓根>\\models``（如 ``D:\\Ai-Files\\GitHub-warehouse\\SoundCatcher\\models``）。

默认走 ``hf-mirror.com`` 镜像，可用 ``--endpoint`` 覆盖。

用法::

    python scripts/download_models.py            # 下载到 config.models_dir
    python scripts/download_models.py --check    # 只校验现有文件
    python scripts/download_models.py --where     # 只打印落点并退出
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from soundcatcher.config import Config  # noqa: E402

CLAP_REPO = "Xenova/clap-htsat-unfused"
OPUS_REPO = "Xenova/opus-mt-zh-en"
OPUS_SUBDIR = "opus-mt-zh-en"
DEFAULT_ENDPOINT = "https://hf-mirror.com"

# 源路径 → 本地文件名（CLAP，落在 models/ 根）
CLAP_FILES: dict[str, str] = {
    "config.json": "config.json",
    "preprocessor_config.json": "preprocessor_config.json",
    "tokenizer_config.json": "tokenizer_config.json",
    "special_tokens_map.json": "special_tokens_map.json",
    "tokenizer.json": "tokenizer.json",
    "vocab.json": "vocab.json",
    "merges.txt": "merges.txt",
    "onnx/audio_model.onnx": "onnx_audio_model.onnx",
    "onnx/text_model.onnx": "onnx_text_model.onnx",
}

# 源路径 → 本地文件名（OPUS-MT，落在 models/opus-mt-zh-en/）
#
# 注意：不要下载或使用独立的 source.spm / target.spm——Xenova 这套导出是 Marian
# 的 65001 词表，而那两个 spm 文件是 32000 词表，喂给模型会解出乱码。分词一律用
# 仓库自带的 tokenizer.json。
OPUS_FILES: dict[str, str] = {
    "config.json": "config.json",
    "generation_config.json": "generation_config.json",
    "tokenizer.json": "tokenizer.json",
    "onnx/encoder_model.onnx": "onnx_encoder_model.onnx",
    "onnx/decoder_model_merged.onnx": "onnx_decoder_model_merged.onnx",
}

# 预期最小体积（MB），用于识别下载中断导致的残缺文件
MIN_MB: dict[str, float] = {
    "onnx_audio_model.onnx": 100.0,
    "onnx_text_model.onnx": 450.0,
    "onnx_encoder_model.onnx": 180.0,
    "onnx_decoder_model_merged.onnx": 200.0,
}

MODELS = Config.default().models_dir

# (repo, 源路径, 目标目录, 本地文件名)
JOBS: list[tuple[str, str, Path, str]] = (
    [(CLAP_REPO, src, MODELS, dst) for src, dst in CLAP_FILES.items()]
    + [(OPUS_REPO, src, MODELS / OPUS_SUBDIR, dst) for src, dst in OPUS_FILES.items()]
)


def download(endpoint: str, force: bool = False) -> int:
    failures = 0
    for repo, src, folder, dst in JOBS:
        folder.mkdir(parents=True, exist_ok=True)
        out = folder / dst
        if out.exists() and not force and _ok(out):
            print(f"[skip] {_rel(out)}（已存在）")
            continue
        url = f"{endpoint}/{repo}/resolve/main/{src}"
        print(f"[get ] {_rel(out)} ← {url}")
        try:
            tmp = out.with_suffix(out.suffix + ".part")
            _fetch(url, tmp)
            tmp.replace(out)
            if not _ok(out):
                print(f"[warn] {dst} 体积异常，可能不完整")
                failures += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[fail] {dst}: {exc}")
            failures += 1
    return failures


def _fetch(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "soundcatcher/0.1"})
    with urllib.request.urlopen(req, timeout=600) as resp, open(dest, "wb") as fh:
        while chunk := resp.read(1 << 20):
            fh.write(chunk)


def _rel(path: Path) -> str:
    """相对 MODELS 的短路径；不在其下则退回绝对路径。"""
    try:
        return str(path.relative_to(MODELS))
    except ValueError:
        return str(path)


def _ok(path: Path) -> bool:
    need = MIN_MB.get(path.name)
    if need is None:
        return path.stat().st_size > 0
    return path.stat().st_size / (1024 * 1024) >= need


def check() -> int:
    missing = []
    for _repo, _src, folder, dst in JOBS:
        p = folder / dst
        status = "OK" if p.exists() and _ok(p) else "MISSING/BAD"
        size = f"{p.stat().st_size / (1024*1024):.1f}MB" if p.exists() else "-"
        print(f"[{status:>12}] {_rel(p):36} {size}")
        if status != "OK":
            missing.append(dst)
    return len(missing)


def main() -> None:
    ap = argparse.ArgumentParser(description="下载 CLAP 与 OPUS-MT ONNX 模型")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="HF 镜像地址")
    ap.add_argument("--force", action="store_true", help="强制重新下载")
    ap.add_argument("--check", action="store_true", help="只校验现有文件")
    ap.add_argument("--where", action="store_true", help="只打印模型落点并退出")
    args = ap.parse_args()

    if args.where:
        print(f"models_dir = {MODELS}")
        print(f"exists     = {MODELS.is_dir()}")
        sys.exit(0)

    if args.check:
        print(f"models_dir = {MODELS}\n")
        sys.exit(1 if check() else 0)

    MODELS.mkdir(parents=True, exist_ok=True)
    print(f"models_dir = {MODELS}\n")
    bad = download(args.endpoint, force=args.force)
    if bad:
        print(f"\n完成，但有 {bad} 个文件异常，请重试。")
        sys.exit(1)
    print("\n全部模型文件就绪。")


if __name__ == "__main__":
    main()
