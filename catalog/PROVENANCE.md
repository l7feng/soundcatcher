# UCS 分类目录数据来源（PROVENANCE）

本目录是 SoundCatcher **UCS 自动分类（任务 1.14）** 的静态语料，全部可追溯、可重建。

## `ucs_v8.2.1.csv` —— 主数据（英文，官方全表）

- **内容**：Universal Category System (UCS) v8.2.1 英文全表，753 个子分类 × 6 列（Category / SubCategory / CatID / CatShort / Explanations / Synonyms）。
- **来源**：官方 UCS 资源（https://universalcategorysystem.com 的 "UCS v8.2.1 Full List"），经开源仓库 `jmrsound/ucs-tools`（MIT，仅作格式工具）随仓附带，见其 `src/ucs_tools/data/PROVENANCE.md`。
- **版本**：8.2.1（列表最终版，2024-01 发布，修正 WOOD-HANDLE → WOODHndl 等）。
- **许可**：**公共领域**（public domain），自由使用无限制。UCS 由 Tim Nielsen / Justin Drury 等发起。
- **本机副本**：`D:\Ai-Files\GitHub-warehouse\SoundCatcher\Reference\ucs-tools\src\ucs_tools\data\ucs_v8.2.1.csv`（工具版本，可随时重新拷贝覆盖，两者应一致）。

## `ucs-zh-en.tsv` —— 中文侧（补充，按 CatID 合并）

- **内容**：Category / SubCategory / CatID / CatShort / Category_zh / SubCategory_zh / Synonyms_zh，**753 行**（与官方英文表 CatID 一一对应，覆盖全量）。
- **来源**：本库技能 `ucs-sound-naming` 的 `references/ucs-zh-en.tsv`（由官方中文翻译与社区 Agent 指令整理，2026-08-20 修复过一批数据问题，见该技能 `references/known-conflicts.md`）。
- **用途**：与官方英文表按 **CatID** 精确合并，给全部分类结果提供中文显示名与中文同义词标签。
- **已知数据问题**：`AMBNaut` 官方发布包字面为 `Platf`（官方人工表笔误），行业实际用 `AMBNaut`，本 TSV 已按 `AMBNaut` 修正（见 known-conflicts.md C1）。

## 生成物（运行时派生，不入本目录）

- `data/ucs/prototypes.npy` —— 753×512 原型向量矩阵（`soundcatcher ucs init` 生成，可随时重建）
- `data/ucs/catalog.json` —— 与 prototypes.npy 对齐的条目元数据（catid / 中英文名 / 同义词头部）

> 本目录是**静态语料**（公共领域数据 + 中文翻译），不是 `data/` 下的派生产物；源音频只读红线不受影响。