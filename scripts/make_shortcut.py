"""在桌面创建 SoundCatcher 快捷方式（无黑窗启动）。

设计：
- 目标不是 ``soundcatcher-gui.exe``（console 包装器 → 双击弹黑窗），而是
  ``.venv/Scripts/pythonw.exe -m soundcatcher.gui.app``（无控制台）。
- ``WorkingDirectory`` 设为项目根，QML 的相对路径与 ``config.py`` 的默认值才成立。
- 图标：优先用 ``assets/icon.ico``（有就用），没有则用 pythonw 自带图标。
- **零新依赖**：走 PowerShell 的 ``WScript.Shell`` COM，不引 pywin32。
- **幂等**：已存在同名快捷方式则覆盖（COM 的 save() 语义）。

用法::

    python scripts/make_shortcut.py            # 在桌面创建
    python scripts/make_shortcut.py --remove   # 删除桌面的那个
    python scripts/make_shortcut.py --check    # 只检查，不写
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SHORTCUT_NAME = "SoundCatcher.lnk"
ICON = PROJECT / "assets" / "icon.ico"


def desktop_dir() -> Path:
    """桌面路径：优先 OneDrive 重定向后的 Desktop，再回退常规位置。"""
    candidates: list[Path] = []
    onedrive = os.environ.get("OneDrive")
    if onedrive:
        candidates += [Path(onedrive) / "Desktop", Path(onedrive) / "桌面"]
    home = Path.home()
    candidates += [home / "Desktop", home / "桌面"]
    for c in candidates:
        if c.is_dir():
            return c
    return home / "Desktop"


def _ps(script: str) -> subprocess.CompletedProcess:
    """跑一段 PowerShell（-NoProfile 免用户配置干扰）。

    **必须落临时 .ps1 再 -File 执行**，不能走 `-Command -` 读 stdin：
    实测 stdin 方式返回空 stdout 且无报错（本机 PowerShell 5.1 不吃这种用法）。
    文件用 UTF-8 **BOM** 写 —— 否则 PS 5.1 按 ANSI 读，中文备注会乱码。
    """
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".ps1", prefix="sc-lnk-")
    os.close(fd)
    p = Path(path)
    try:
        p.write_bytes(b"\xef\xbb\xbf" + script.encode("utf-8"))  # UTF-8 BOM
        return subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(p)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    finally:
        p.unlink(missing_ok=True)


def make(remove: bool = False, check: bool = False) -> int:
    if os.name != "nt":
        print("! 仅支持 Windows（快捷方式依赖 COM 的 WScript.Shell）")
        return 1

    lnk = desktop_dir() / SHORTCUT_NAME
    pyw = PROJECT / ".venv" / "Scripts" / "pythonw.exe"

    print(f"项目根      : {PROJECT}")
    print(f"pythonw.exe : {pyw}  {'[存在]' if pyw.exists() else '[缺失!]'}")
    print(f"快捷方式    : {lnk}")
    print(f"图标        : {ICON}  {'[存在]' if ICON.exists() else '[无，用默认]'}")

    if check:
        print(f"\n检查结果：快捷方式{'存在' if lnk.exists() else '不存在'}")
        return 0

    if remove:
        if lnk.exists():
            lnk.unlink()
            print(f"\n已删除：{lnk}")
        else:
            print("\n本来就不存在，无需删除")
        return 0

    if not pyw.exists():
        print("\n! 找不到 .venv\\Scripts\\pythonw.exe —— 请先建虚拟环境：")
        print("    python -m venv .venv")
        print(r"    .venv\Scripts\pip install -e .")
        return 1

    # PowerShell 里用单引号包裹路径（避免反斜杠被当转义），内部再把 ' 翻倍转义
    def q(p: Path | str) -> str:
        return "'" + str(p).replace("'", "''") + "'"

    icon_line = (
        f"$sc.IconLocation = {q(ICON)}\n" if ICON.exists() else ""
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut({q(lnk)})
$sc.TargetPath = {q(pyw)}
$sc.Arguments = '-m soundcatcher.gui.app'
$sc.WorkingDirectory = {q(PROJECT)}
$sc.Description = 'SoundCatcher - 本地 AI 音效库（离线语义搜索）'
{icon_line}$sc.Save()
Write-Output 'SAVED'
"""
    r = _ps(script)
    if "SAVED" in (r.stdout or ""):
        print(f"\n[OK] 快捷方式已创建：{lnk}")
        print("     双击即可无黑窗启动。")
        return 0

    print("\n! 创建失败")
    print("  stdout:", (r.stdout or "").strip())
    print("  stderr:", (r.stderr or "").strip())
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="创建/删除 SoundCatcher 桌面快捷方式")
    ap.add_argument("--remove", action="store_true", help="删除桌面快捷方式")
    ap.add_argument("--check", action="store_true", help="只检查，不写盘")
    args = ap.parse_args()
    return make(remove=args.remove, check=args.check)


if __name__ == "__main__":
    sys.exit(main())
