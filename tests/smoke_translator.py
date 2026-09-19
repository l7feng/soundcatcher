"""OPUS-MT 翻译桥冒烟测试。"""

from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from soundcatcher.translator import OpusTranslator, has_cjk  # noqa: E402

TESTS = [
    "玻璃破碎，带回响的",
    "错误警告提示音",
    "闹钟铃声",
    "沉重的金属门关闭声",
    "低沉的爆炸轰鸣",
    "鸟叫声",
]


def main() -> None:
    tr = OpusTranslator(ROOT / "models" / "opus-mt-zh-en")
    for zh in TESTS:
        t0 = time.perf_counter()
        en = tr.translate(zh)
        dt = time.perf_counter() - t0
        det = "CJK" if has_cjk(zh) else "---"
        print(f"[{det}] {zh}  ->  {en}   ({dt:.2f}s)")


if __name__ == "__main__":
    main()
