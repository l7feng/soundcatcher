"""静态校验：main.qml 里引用的每个 ``backend.<name>`` 都必须真的存在于
AppBackend 的 Qt 元对象中（属性 / 槽 / Q_INVOKABLE）。

**为什么需要这个测试**：PySide6 里 `backend.xxxx` 写错名字**不会报错**，只会静默
得到 `undefined`。踩过的真实案例：`searching = Property(...)` 与类里已有的同名
`@property` 冲突，元对象里注册成了 `searching_prop`，于是 QML 里
`backend.searching` 一直是 undefined —— 忙碌指示器不转、状态文案不切，
只在启动时飘一条 `Unable to assign [undefined] to bool` 就算过去了。

这个测试把「靠肉眼发现」变成「CI 可拦」，同类问题以后直接红。

用法::

    python tests/test_backend_contract.py     # 结果写 tests/_backend_contract.log
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

QML = PROJECT / "src" / "soundcatcher" / "gui" / "main.qml"
I18N = PROJECT / "src" / "soundcatcher" / "gui" / "I18n.qml"
THEME = PROJECT / "src" / "soundcatcher" / "gui" / "Theme.qml"
LOG = Path(__file__).resolve().parent / "_backend_contract.log"

fails: list[str] = []
_lines: list[str] = []


def out(m: str = "") -> None:
    _lines.append(m)
    try:
        print(m, flush=True)
    except Exception:  # noqa: BLE001
        pass


def chk(cond: bool, msg: str) -> None:
    out(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def main() -> int:
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    app = QApplication(sys.argv)  # noqa: F841 (构造 backend 需要)
    from soundcatcher.gui.backend import AppBackend  # noqa: PLC0415

    b = AppBackend()
    mo = b.metaObject()

    # ---------- 收集元对象里可用的名字 ----------
    qt_props: set[str] = set()
    for i in range(mo.propertyCount()):
        qt_props.add(mo.property(i).name())

    qt_methods: set[str] = set()
    for i in range(mo.methodCount()):
        m = mo.method(i)
        qt_methods.add(bytes(m.name()).decode("utf-8"))
    # 信号也算可引用（Connections 的 target 回调靠它）
    qt_signals: set[str] = set()
    for i in range(mo.methodCount()):
        m = mo.method(i)
        if m.methodType() == m.MethodType.Signal:
            qt_signals.add(bytes(m.name()).decode("utf-8"))

    known = qt_props | qt_methods

    out("=== AppBackend 元对象 ===")
    out("  属性 %d 个，方法 %d 个（其中信号 %d 个）" % (len(qt_props), len(qt_methods), len(qt_signals)))

    # ---------- 扫描 QML 里的 backend.<name> ----------
    src = QML.read_text(encoding="utf-8")
    # 去掉行注释，避免注释里的示例被当真实引用
    src_nc = re.sub(r"//[^\n]*", "", src)
    refs = sorted(set(re.findall(r"\bbackend\.([A-Za-z_][A-Za-z0-9_]*)", src_nc)))
    out("\n=== main.qml 引用 backend 成员 %d 个 ===" % len(refs))

    missing = [r for r in refs if r not in known and "on" + r[0].upper() + r[1:] not in qt_signals]
    for r in refs:
        mark = "OK " if r not in missing else "MISSING"
        out("  [%s] backend.%s" % (mark, r))

    out("\n=== 校验 ===")
    chk(not missing, "所有 backend.<name> 均存在于元对象（缺失：%s）" % (missing or "无"))

    # ---------- 守护：Property 声明不能与已有同名属性冲突 ----------
    out("\n=== Property 声明 vs 类属性冲突（本 bug 的根因） ===")
    from PySide6.QtCore import Property  # noqa: PLC0415

    shadowed: list[str] = []
    for name, val in type(b).__dict__.items():
        if isinstance(val, Property) and mo.indexOfProperty(name) < 0:
            shadowed.append(name)
    chk(not shadowed, "无被遮蔽的 Property（遮蔽项：%s）" % (shadowed or "无"))
    if shadowed:
        out("    说明：这些 Property 的变量名未进元对象，多半被同名 @property 顶掉了；")
        out("    修法＝显式 `xxx = Property(..., name='真名')` 或统一变量名与属性名。")

    # ---------- i18n：QML 用到的 key 必须在 I18n 表里有 ----------
    out("\n=== I18n key 覆盖 ===")
    i18n_src = I18N.read_text(encoding="utf-8")
    keys = set(re.findall(r'"([a-z][a-zA-Z0-9_.]*)"\s*:', i18n_src))
    used = set(re.findall(r'I18n\.t\(\s*"([^"]+)"', src_nc))
    # 带 %n 参数的调用形如 I18n.t("a.b", x)，上面的正则已能抓到 key
    unknown = sorted(k for k in used if k not in keys)
    out("  I18n 表 %d 个 key；QML 使用 %d 个" % (len(keys), len(used)))
    chk(not unknown, "无未定义 i18n key（缺失：%s）" % (unknown or "无"))

    # 反向：表里有但没人用的 key（只报告不判失败，属清理提示）
    unused = sorted(k for k in keys if k not in used)
    if unused:
        out("  （提示）I18n 表内 %d 个 key 当前未被 QML 引用：%s" % (len(unused), unused[:12]))

    # ---------- Theme：QML 用到的 Theme.* token 必须在 Theme.qml 里有 ----------
    out("\n=== Theme token 覆盖 ===")
    theme_src = THEME.read_text(encoding="utf-8")
    t_tokens = set(re.findall(r"property\s+(?:color|real|int|string|bool|var)\s+([A-Za-z_]\w*)", theme_src))
    t_tokens |= set(re.findall(r"readonly\s+property\s+(?:color|real|int|string|bool|var)\s+([A-Za-z_]\w*)", theme_src))
    t_tokens |= set(re.findall(r"function\s+([A-Za-z_]\w*)", theme_src))
    t_used = set(re.findall(r"\bTheme\.([A-Za-z_]\w*)", src_nc))
    t_missing = sorted(k for k in t_used if k not in t_tokens)
    out("  Theme 提供 %d 个 token；QML 使用 %d 个" % (len(t_tokens), len(t_used)))
    chk(not t_missing, "无未定义 Theme token（缺失：%s）" % (t_missing or "无"))

    # ---------- property alias 不能指向单例（QML 硬限制） ----------
    out("\n=== property alias 指向单例（会导致整份 QML 加载失败） ===")
    bad_alias = re.findall(r"property\s+alias\s+\w+\s*:\s*(Theme|I18n)\s*\.", src_nc)
    chk(not bad_alias, "无 property alias 指向 Theme/I18n（发现：%s）" % (bad_alias or "无"))

    out("\n=== RESULT ===")
    if fails:
        for f in fails:
            out("  FAIL: " + f)
        code = 1
    else:
        out("  BACKEND CONTRACT OK")
        code = 0
    LOG.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    try:
        rc = main()
    except BaseException:  # noqa: BLE001
        import traceback  # noqa: PLC0415

        _lines.append(traceback.format_exc())
        LOG.write_text("\n".join(_lines) + "\n", encoding="utf-8")
        rc = 3
    sys.exit(rc)
