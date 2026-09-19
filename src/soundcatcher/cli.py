"""SoundCatcher 命令行入口（阶段 1：扫描 / 文本搜索 / 以声搜声 / 统计）。

用法示例::

    soundcatcher scan "D:\\音效库"
    soundcatcher search "玻璃破碎，带回响的" --mode hybrid
    soundcatcher similar "D:\\音效库\\ref.wav" --limit 10
    soundcatcher stats
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from . import db
from .config import Config
from .embedder import ClapEmbedder
from .indexer import Indexer, VectorIndex
from .search import SearchResult, Searcher
from .translator import OpusTranslator
from .ucs import PROTO_VERSION, UcsCatalog, UcsClassifier

# Windows 控制台按 UTF-8 输出，避免中文乱码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # pragma: no cover
        pass

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="SoundCatcher —— 本地优先的 AI 音效库管理工具（阶段 1 CLI）",
)
console = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


def _open_library(cfg: Config):
    """打开索引库三件套：SQLite 连接、faiss 索引、嵌入器。"""
    cfg.ensure()
    conn = db.connect(cfg.db_path)
    db.init_db(conn)
    embedder = ClapEmbedder(cfg.models_dir)
    index = VectorIndex(cfg.index_path)
    return conn, index, embedder


def _translator_factory(cfg: Config):
    """惰性翻译器工厂；翻译模型缺失时返回 None（中文查询将退化为原样检索）。"""
    model_dir = cfg.translator_dir
    if not (model_dir / "onnx_encoder_model.onnx").exists():
        console.print("[yellow]未找到中英翻译模型，中文查询将不做翻译。[/]")
        console.print(f"[dim]期望位置：{model_dir}[/]")
        return None

    def build() -> OpusTranslator:
        return OpusTranslator(model_dir)

    return build


def _print_results(results: list[SearchResult], title: str) -> None:
    if not results:
        console.print("[yellow]没有匹配结果。[/]")
        return
    table = Table(title=title, show_lines=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("文件名", overflow="fold")
    table.add_column("目录", style="dim", overflow="fold")
    table.add_column("时长", justify="right")
    table.add_column("分数", justify="right", style="cyan")
    table.add_column("来源", style="dim")
    table.add_column("标签", style="green", overflow="fold")
    for i, r in enumerate(results, start=1):
        table.add_row(
            str(i),
            r.filename,
            Path(r.path).parent.name,
            r.duration_str,
            f"{r.score:.3f}",
            r.source,
            ", ".join(r.tags),
        )
    console.print(table)


# ---------------------------------------------------------------------------
# 命令
# ---------------------------------------------------------------------------


@app.command()
def scan(
    dirs: Annotated[list[Path], typer.Argument(help="要索引的目录或音频文件")],
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="输出调试日志")] = False,
) -> None:
    """扫描目录并增量建立/更新索引。"""
    _setup_logging(verbose)
    cfg = Config.default()
    conn, index, embedder = _open_library(cfg)
    indexer = Indexer(conn, index, embedder)

    console.print(f"[bold]索引库[/] {cfg.db_path}")
    console.print(f"[bold]扫描目标[/] {', '.join(str(d) for d in dirs)}")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as prog:
        task = prog.add_task("准备中…", total=None)

        def cb(done: int, total: int, current: str) -> None:
            prog.update(
                task,
                total=total,
                completed=done,
                description=f"索引 {Path(current).name[:40]}",
            )

        stats = indexer.scan(dirs, progress=cb)

    console.print(f"[green]{stats.summary()}[/]")
    if stats.errors:
        console.print(f"[red]最近 {min(len(stats.errors), 5)} 条错误：[/]")
        for path, err in stats.errors[:5]:
            console.print(f"  [dim]{path}[/] → {err[:120]}")


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="查询文本（中英文均可）")],
    mode: Annotated[
        str, typer.Option("--mode", "-m", help="semantic | keyword | hybrid")
    ] = "hybrid",
    limit: Annotated[int, typer.Option("--limit", "-n", help="返回条数")] = 20,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """文本搜索（默认混合模式：语义 + 关键词）。"""
    _setup_logging(verbose)
    cfg = Config.default()
    conn, index, embedder = _open_library(cfg)
    searcher = Searcher(conn, index, embedder, translator_factory=_translator_factory(cfg))

    with console.status("检索中…"):
        results = searcher.search(query, mode=mode, limit=limit)
    if searcher.last_translation:
        console.print(f"[dim]中文查询已译为英文：[/][cyan]{searcher.last_translation}[/]")
    _print_results(results, f'搜索“{query}”（{mode}）')


@app.command()
def similar(
    audio: Annotated[Path, typer.Argument(help="参考音频文件路径")],
    limit: Annotated[int, typer.Option("--limit", "-n", help="返回条数")] = 20,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """以声搜声：找与参考音频声学相似的素材。"""
    _setup_logging(verbose)
    cfg = Config.default()
    conn, index, embedder = _open_library(cfg)
    searcher = Searcher(conn, index, embedder)

    with console.status("检索中…"):
        results = searcher.search_similar(audio, limit=limit)
    _print_results(results, f"与 {audio.name} 相似")


@app.command()
def stats(
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """显示索引库统计。"""
    _setup_logging(verbose)
    cfg = Config.default()
    conn, index, embedder = _open_library(cfg)
    s = db.stats(conn)
    console.print(f"[bold]索引库[/] {cfg.db_path}")
    console.print(f"  文件总数：{s['total']}")
    console.print(f"  已嵌入：  {s['embedded']}")
    console.print(f"  失败：    {s['failed']}")
    console.print(f"  向量索引：{len(index)} 条")


@app.command()
def version() -> None:
    """显示版本。"""
    from . import __version__

    console.print(f"SoundCatcher {__version__}")


# ---------------------------------------------------------------------------
# UCS 自动分类
# ---------------------------------------------------------------------------

ucs_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="UCS 自动分类（753 类零样本 + 置信度）",
)
app.add_typer(ucs_app, name="ucs")


@ucs_app.command("init")
def ucs_init(
    force: Annotated[bool, typer.Option("--force", help="忽略已存在原型，强制重建")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """构建 753 类原型矩阵（一次性；文本塔嵌入，约 1~2 分钟 CPU）。"""
    _setup_logging(verbose)
    cfg = Config.default()
    proto_path = cfg.ucs_dir / "prototypes.npy"
    if proto_path.exists() and not force:
        console.print(
            f"[yellow]原型已存在：{proto_path}[/]\n"
            "[yellow]改动提示词模板或模型后请用 --force 重建。[/]"
        )
        return

    catalog = UcsCatalog(cfg.catalog_dir)
    console.print(f"[bold]UCS 目录[/] {len(catalog)} 类（{cfg.catalog_dir.name}/）")
    embedder = ClapEmbedder(cfg.models_dir)

    import time

    t0 = time.time()
    with console.status(f"文本塔嵌入 {len(catalog) * 3} 条提示词…"):
        matrix = catalog.build_prototypes(embedder, cfg.ucs_dir)
    conn = db.connect(cfg.db_path)
    db.init_db(conn)
    db.set_meta(conn, "ucs_proto_version", str(PROTO_VERSION))
    conn.commit()
    conn.close()

    n_zh = sum(1 for e in catalog.entries if e.category_zh or e.subcategory_zh)
    console.print(
        f"[green]原型已构建：[/]{matrix.shape[0]}×512 = {cfg.ucs_dir / 'prototypes.npy'}"
    )
    console.print(f"[dim]含中文显示/同义词条数：{n_zh} / {len(catalog)}；耗时 {time.time() - t0:.1f}s[/]")


@ucs_app.command("tag")
def ucs_tag(
    topk: Annotated[int, typer.Option("--topk", "-k", help="每文件保留的分类数")] = 3,
    min_score: Annotated[float, typer.Option("--min-score", help="标签最低余弦分（低于则只存标签不写 tags）")] = 0.0,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """对库内已嵌入文件做 UCS 分类，写 ucs_labels 表 + 自动标签。"""
    _setup_logging(verbose)
    cfg = Config.default()

    try:
        classifier = UcsClassifier.from_dir(cfg.ucs_dir, top_k=topk)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/]")
        console.print("[yellow]先运行 [bold]soundcatcher ucs init[/bold] 构建原型。[/]")
        raise typer.Exit(1)

    conn = db.connect(cfg.db_path)
    db.init_db(conn)
    index = VectorIndex(cfg.index_path)

    rows = conn.execute(
        "SELECT id, filename FROM files WHERE embedded=1 ORDER BY id"
    ).fetchall()
    if not rows:
        console.print("[yellow]库中还没有已嵌入的文件，先运行 [bold]soundcatcher scan[/bold]。[/]")
        return

    ids = [int(r["id"]) for r in rows]
    with console.status(f"重建 {len(ids)} 条向量并分类…"):
        vecs = index.vectors_by_id(ids)
        results = classifier.classify_vectors(vecs)

    n_tagged = 0
    n_below = 0
    for fid, res in zip(ids, results):
        # ucs_labels：top-k 全部落库（幂等更新）
        for entry, score, conf in res:
            conn.execute(
                """INSERT INTO ucs_labels(file_id, catid, confidence, source)
                   VALUES (?,?,?,?)
                   ON CONFLICT(file_id, catid) DO UPDATE SET
                       confidence=excluded.confidence, source=excluded.source""",
                (fid, entry.catid, float(score), "classifier"),
            )
        top = res[0]
        if float(top[1]) >= min_score:
            e = top[0]
            db.add_tag(conn, fid, f"ucs:{e.catid}", auto=True)
            db.add_tag(conn, fid, f"ucs:{e.display_zh}", auto=True)
            for s in e.synonyms_zh[:3]:
                db.add_tag(conn, fid, s, auto=True)
            n_tagged += 1
        else:
            n_below += 1
        db.refresh_fts_tags(conn, fid)
    conn.commit()

    console.print(
        f"[green]UCS 分类完成：[/]{len(ids)} 个文件 → {len(classifier.catalog)} 类"
        f"，写入标签 {n_tagged}，低于阈值未写标签 {n_below}"
    )
    console.print(f"[dim]结果表 ucs_labels 已更新（source=classifier），tags 已进 FTS。[/]")

    table = Table(title="UCS 分类抽样（前 12）", show_lines=False)
    table.add_column("文件名", overflow="fold")
    table.add_column("Top1 CatID", style="cyan")
    table.add_column("分类（中）", style="green")
    table.add_column("余弦", justify="right")
    table.add_column("置信", justify="right")
    for r, res in zip(rows[:12], results[:12]):
        e, score, conf = res[0]
        table.add_row(r["filename"], e.catid, e.display_zh, f"{score:.3f}", f"{conf:.0%}")
    console.print(table)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    app()
