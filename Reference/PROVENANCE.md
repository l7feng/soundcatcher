# Reference 第三方参考源码溯源（PROVENANCE）

本目录存放 `08-Sound-library`（SoundCatcher）开发期使用的**第三方只读参考**，均非本项目代码。
2026-09-22 随工程从 `D:\Ai-Files\App-Project\Sound-library\Reference\` 迁入仓内。
**红线：只读思路，不搬代码**（AGPL 项目尤其）；升级方式＝重新下载覆盖。

## 1. `deep-cuts\` —— Deep Cuts

| 项 | 值 |
|---|---|
| 用途 | 「本地优先 + 离线 ML 索引」音频分析桌面应用的参考：CLAP 嵌入、UMAP 音乐地图、sidecar `.dc.json` 持久化、DSP 分析流水线、分块并发分析引擎 |
| 上游 | https://github.com/robertolupi/deep-cuts |
| 版本 | **v0.1.8**（CHANGELOG 最新条目日期 2026-06-08） |
| 作者 | Roberto Lupi |
| 技术栈 | Tauri 2 + Rust（`src-tauri/`）+ Svelte 前端；含 git submodule `third_party/llama.cpp` |
| 许可 | **AGPL-3.0** ⚠️ 传染性 —— 只读思路、不搬代码 |
| 本机形态 | **无 `.git` 的下载快照**（368 文件 / 97.89 MB）。无法回溯具体 commit，版本以上游 `package.json`、`Cargo.toml`、`tauri.conf.json` 三处一致的 `0.1.8` 为准 |
| 体积说明 | `src-tauri/tests/fixtures/` 占 **78 MB**，是上游自带的**测试音频**（wav 38.6 / flac 31.7 / mp3 / m4a），非源码 |

## 2. `semantic-audio-search\` —— Semantic Audio Search

| 项 | 值 |
|---|---|
| 用途 | 自托管语义检索栈参考：CLAP 嵌入 + 向量库 + 关键词混合排序 + 增量重扫 |
| 上游 | https://github.com/TaaroBravo/semantic-audio-search |
| 技术栈 | FastAPI（Python 3.11+）· CLAP embeddings · Qdrant · SQLite · Gradio · Docker |
| 许可 | **MIT** —— 可搬代码（本项目仅在思路上参考，未搬运） |
| 本机形态 | 无 `.git` 的下载快照（16 文件 / 0.38 MB） |

## 3. `ucs-tools\` —— UCS Tools

| 项 | 值 |
|---|---|
| 用途 | UCS（Universal Category System）分类工具参考；本项目 `catalog/ucs_v8.2.1.csv` 的取数来源 |
| 上游 | https://github.com/jmrsound/ucs-tools |
| 版本 | 无 tag；HEAD = **`2e307eb9aa4743a7a666426a9f70dcd08d393b40`**（2026-07-30），CHANGELOG 处于 `[Unreleased]` |
| 许可 | MIT（UCS 语料本身为公共领域） |
| 本机形态 | **完整 git 仓**（保留 `.git`，remote = `origin`）→ 版本可回溯；72 文件 / 3.46 MB |

## 维护约定

- 三个参考目录**不入版本控制**（见仓根 `.gitignore` 的 `Reference/`）。
- `ucs-tools` 保留 `.git`，可直接 `git -C Reference/ucs-tools pull` 升级，升级后把新 HEAD 记到本表。
- `deep-cuts` 与 `semantic-audio-search` 是无 `.git` 快照，升级＝重新下载覆盖，同样回来更新本表。
- **自动化同步任务（每天 00:00 的「Repos 仓库每日同步检查」）必须整体跳过 `Reference/` 下三个参考目录**：只读、永不 commit、永不 push。`ucs-tools` 的 remote 指向第三方 `jmrsound/ucs-tools`，本机无推送权限，任何自动写入都属越界；其余两份是无 `.git` 快照，同样不属本仓待提交内容。（2026-11-09 补）

---

> 最后核对：2026-09-22
