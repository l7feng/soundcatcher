# SoundCatcher

本地优先、无付费墙的 AI 音效库管理工具。一句话搜音效（CLAP 语义搜索）、以声搜声、
UCS 自动分类、波形预览——数据不出本机，可完全离线运行。

> 当前进度：**阶段 1（CLI 核心）已完成**——扫描索引 / 文本语义搜索 / 以声搜声 / UCS 分类打标已跑通；
> **阶段 2（GUI 桌面）进行中**——PySide6 + QML 应用（搜索 / 播放 / 波形）已可跑。

## 技术栈

| 层 | 选型 |
|---|---|
| 语言 | Python 3.12 |
| 音频 I/O | PyAV（ffmpeg 绑定，全格式） |
| 特征 | 纯 numpy 复刻 transformers `ClapFeatureExtractor`（免 torch 依赖） |
| 嵌入 | CLAP `laion/clap-htsat-unfused`（ONNX 双塔，512 维共享空间） |
| 推理 | onnxruntime（CPU，可切 DirectML GPU） |
| 向量检索 | faiss `IndexIDMap2(IndexFlatIP)`（精确余弦，10 万级毫秒） |
| 元数据 | SQLite（WAL + FTS5 关键词检索） |

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
python scripts\download_models.py        # 下载 CLAP ONNX（~600MB，走 hf-mirror）
```

## 使用

```powershell
# 索引一个音效库目录（增量：未变更的文件自动跳过）
.\.venv\Scripts\soundcatcher.exe scan "D:\音效库"

# 语义搜索（中英文均可）
.\.venv\Scripts\soundcatcher.exe search "玻璃破碎，带回响的"

# 以声搜声
.\.venv\Scripts\soundcatcher.exe similar "D:\音效库\某素材.wav"

# 关键词模式 / 混合模式（默认）
.\.venv\Scripts\soundcatcher.exe search "door slam" --mode keyword

# 库统计
.\.venv\Scripts\soundcatcher.exe stats

# 图形界面（阶段 2；只读会话，可与命令行扫描并存）
.\.venv\Scripts\soundcatcher-gui.exe
```

> GUI 数据目录默认与 CLI 相同（`data/`）；可用环境变量 `SOUNDCATCHER_DATA_HOME`
> 指向其他目录（如独立测试库）。GUI 为**严格只读**：查询 / 播放 / 波形不写库，
> 与后台扫描进程并发安全。

## 目录结构

```
src/soundcatcher/
  cli.py       命令行入口（scan / search / similar / stats / ucs）
  gui/         PySide6 + QML 界面（app.py 入口 / backend.py 三线程后端 / main.qml）
  config.py    路径与运行配置
  audio.py     PyAV 探测与解码（全格式 → 48kHz 单声道）
  features.py  纯 numpy 的 CLAP mel 特征抽取
  embedder.py  CLAP ONNX 双塔嵌入
  indexer.py   faiss 索引 + 扫描管线
  search.py    语义 / 关键词 / 混合检索
  db.py        SQLite 元数据层
models/        模型文件（gitignore，用脚本下载）
data/          运行时产物：library.db + index/vectors.faiss（gitignore）
data-test/     GUI 开发用独立测试库（gitignore）
scripts/       download_models / run_scan / make_test_lib / bench_search / screenshot_gui
tests/         探测、冒烟与 GUI 冒烟脚本
```

## 数据安全

索引库（`data/`）只保存**派生数据**——绝不移动、重命名或修改你的源音频文件。
删除 `data/` 即可完全重置，源库毫发无损。
