"""全量扫描的守护式启动器（脱离控制台后台运行）。

用途
----
阶段 1.15 真实库全量续扫需要一个"能跑 4 小时、父会话退出也不死、中文路径不乱码"的启动方式。
- Windows PowerShell 5.1 的 ``Start-Process`` 会把非 ASCII 参数按 ANSI 转写，中文路径会被损坏
  （实测 ``D:\\音效库\\1_FX_循环效果`` 到达子进程时已不是有效目录）。
- 后台子进程挂在父控制台上，父会话一关就会被 CTRL_CLOSE 杀掉。

出路：
1. 目标目录**不从命令行传**：从 ``data/scan_target.txt``（UTF-8）读取，或本脚本 argv[1]。
2. 用 ``Win32_Process.Create``（WMI）启动本脚本，进程无控制台、不属于调用方作业对象。
3. 本脚本自己把 stdout/stderr 重定向到 ``data/scan_runner.log``（UTF-8），
   每 25 个文件写一行心跳进度，异常把 traceback 落盘 ``data/scan_runner.status``。

用法::

    Set-Content -LiteralPath data\\scan_target.txt -Value "D:\\音效库" -Encoding UTF8
    $p = ([wmiclass]"Win32_Process").Create('"<python.exe>" "<repo>\\scripts\\run_scan.py"')
    $p.ProcessId
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
TARGET_FILE = DATA / "scan_target.txt"
LOG_FILE = DATA / "scan_runner.log"
STATUS_FILE = DATA / "scan_runner.status"

sys.path.insert(0, str(REPO / "src"))

# -- 输出重定向：全部进 scan_runner.log（UTF-8），控制台一概不写 ------------
_log_handle = open(LOG_FILE, "w", encoding="utf-8")
sys.stdout = _log_handle
sys.stderr = _log_handle


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{_now()}  {msg}\n")


def main() -> int:
    # 目标目录：优先 argv[1]，否则 scan_target.txt
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
        log(f"目标目录来自 argv[1]：{target}")
    else:
        if not TARGET_FILE.exists():
            log(f"!! 找不到目标文件 {TARGET_FILE}")
            return 2
        target = Path(TARGET_FILE.read_text(encoding="utf-8").strip())
        log(f"目标目录来自 scan_target.txt：{target}")

    if not target.is_dir():
        log(f"!! 目标不是有效目录：{target}")
        return 2

    from soundcatcher.config import Config

    cfg = Config.default()
    cfg.ensure()

    from soundcatcher import db
    from soundcatcher.embedder import ClapEmbedder
    from soundcatcher.indexer import Indexer, VectorIndex

    import logging

    logging.basicConfig(level=logging.DEBUG, stream=_log_handle, format="%(levelname)s %(name)s: %(message)s")

    log(f"就绪：models={cfg.models_dir} db={cfg.db_path}")
    conn = db.connect(cfg.db_path)
    db.init_db(conn)
    embedder = ClapEmbedder(cfg.models_dir)
    index = VectorIndex(cfg.index_path)
    indexer = Indexer(conn, index, embedder)
    log(f"载入已有向量 {len(index)} 条，开始扫描 {target}")

    # 一致性护栏：新逻辑「先落 faiss、后提交 DB」下 DB ≤ faiss 恒成立；
    # 若出现 DB > faiss，说明是旧逻辑（先提交后落盘）被杀留下的静默缺口，
    # 把全库 embedded 重置为 0，让本次扫描全量重建向量。
    # 2026-09-18 修订：差值 ≤ commit_every（一批 200 条）时不再推倒全库——
    # 只归零「尾部多出的行」（单进程顺序扫描下 id 单调递增，尾部即最近批次），
    # 下次续扫自动补齐；仅当差值异常大（> 200）才全库重建，避免误伤。
    n_db_embedded = conn.execute(
        "select count(*) from files where embedded=1"
    ).fetchone()[0]
    n_excess = n_db_embedded - len(index)
    if n_excess > 0:
        if 0 < n_excess <= 200:
            log(
                f"!! 一致性小缺口：DB 声称已嵌入 {n_db_embedded} 条 > faiss {len(index)} 条 "
                f"（尾部 {n_excess} 条未落盘）→ 仅归零尾部行，本趟自动补齐"
            )
            conn.execute(
                "update files set embedded=0, error=null where id in "
                "(select id from files where embedded=1 order by id desc limit ?)",
                (n_excess,),
            )
            conn.commit()
        else:
            log(
                f"!! 一致性告警：DB 声称已嵌入 {n_db_embedded} 条 > faiss {len(index)} 条，"
                f"差值 {n_excess} 条异常（>200）→ 重置 embedded 后全量重建"
            )
            conn.execute("update files set embedded=0, error=null where embedded=1")
            conn.commit()
    elif n_db_embedded == len(index):
        log(f"一致性 OK：faiss 与 DB 均为 {len(index)} 条")
    else:
        log(
            f"提示：faiss {len(index)} 条 > DB {n_db_embedded} 条 "
            "（上一次未提交完成的尾部批次，本趟扫描将自动补齐）"
        )

    t0 = datetime.now()

    def cb(done: int, total: int, current: str) -> None:
        log(f"[{done}/{total}] {Path(current).name[:60]}")

    try:
        stats = indexer.scan([target], progress=cb)
    except Exception:
        msg = traceback.format_exc()
        log("!! 扫描异常（traceback 见下）：\n" + msg)
        STATUS_FILE.write_text("failed\n" + msg, encoding="utf-8")
        return 1

    el = datetime.now() - t0
    summary = (
        f"完成 {stats.summary()} | 总文件 {stats.total} | 新增 {stats.added} "
        f"| 更新 {stats.updated} | 跳过 {stats.skipped} | 失败 {stats.failed} "
        f"| 耗时 {el.total_seconds():.0f}s"
    )
    log(summary)
    if stats.errors:
        for path, err in stats.errors[:10]:
            log(f"  [err] {path} → {err[:150]}")
    STATUS_FILE.write_text(f"ok\n{summary}\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())