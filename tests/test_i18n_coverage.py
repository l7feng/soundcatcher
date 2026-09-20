"""扫描 main.qml 里**绕过 i18n 的硬编码界面文案**（漏翻的话切英文会露出中文）。

判定：出现在 `text:` / `placeholderText:` / `ToolTip.text:` / `title:` 等
界面文案位置、且值里含中日韩字符、又没有走 I18n.t(...) 的字面量。

用法::

    python tests/test_i18n_coverage.py     # 结果写 tests/_i18n_coverage.log
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
QML = PROJECT / "src" / "soundcatcher" / "gui" / "main.qml"
LOG = Path(__file__).resolve().parent / "_i18n_coverage.log"

# 明确要展示给用户的文案属性
TEXT_ATTRS = ("text", "placeholderText", "title", "ToolTip.text", "description",
              "informativeText", "subtitle")

CJK = re.compile(r"[\u4e00-\u9fff]")

# 白名单：语言名必须永远用该语言自己的写法（切到英文界面时「中文」这一项
# 仍应显示“中文”，否则用户找不到切回去的入口），所以这里豁免。
ALLOW = {
    (445, "text"),   # 语言菜单：中文
}

lines = []
fails = []


def out(m: str = "") -> None:
    lines.append(m)
    try:
        print(m, flush=True)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    src = QML.read_text(encoding="utf-8")
    raw_lines = src.splitlines()

    hits: list[tuple[int, str]] = []
    for i, ln in enumerate(raw_lines, 1):
        stripped = ln.strip()
        # 跳过注释行
        if stripped.startswith("//"):
            continue
        for attr in TEXT_ATTRS:
            # 匹配  attr: "含中文的字面量"   （单/双引号都认）
            m = re.search(rf"\b{re.escape(attr)}\s*:\s*([\"'])(.*?)\1", ln)
            if not m:
                continue
            val = m.group(2)
            if CJK.search(val) and (i, attr) not in ALLOW:
                hits.append((i, f"{attr}: \"{val}\""))
            break

    out("=== main.qml 硬编码中文文案（应全部走 I18n.t） ===")
    if not hits:
        out("  未发现 —— 界面文案已全部进入 i18n（白名单 %d 项已豁免）" % len(ALLOW))
    for i, s in hits:
        out("  L%-5d %s" % (i, s))

    out("\n=== RESULT ===")
    if hits:
        for i, s in hits:
            fails.append("L%d %s" % (i, s))
        out("  %d 处硬编码中文（切英文时会露出中文）" % len(hits))
        code = 1
    else:
        out("  I18N COVERAGE OK")
        code = 0
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    try:
        rc = main()
    except BaseException:  # noqa: BLE001
        import traceback  # noqa: PLC0415

        lines.append(traceback.format_exc())
        LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rc = 3
    sys.exit(rc)
