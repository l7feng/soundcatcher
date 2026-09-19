"""SoundCatcher GUI 包（阶段 2：PySide6 + QML 桌面应用）。

界面概念对齐 SoundSeeker：
- 顶部工具条：检索模式切换 + 搜索框
- 左侧：库统计 / 收藏 / 历史（UCS 树在后续迭代）
- 中央：结果列表（文件名 / 时长 / 分数 / UCS 标签）
- 底部：播放条 + 波形实时显示

核心设计约束（2026-09-18 定案）：

1. **严格只读会话**：GUI 第一版只读——查询 / 播放 / 波形，绝不写索引库。
   与另一个正在全量续扫的进程可以安全共存（SQLite WAL 多读一写、
   faiss 并发读安全）。后续加入扫描功能时再引入单实例写锁。
2. **常驻模型线程**：CLAP（≈590MB）与翻译桥加载、全部检索推理都在一个
   QThread 内执行，UI 线程零阻塞；SQLite 连接也只在该线程使用。
3. **波形懒加载**：点击结果才解码波形（独立线程），QML Canvas 绘制。
4. 数据目录可用环境变量 ``SOUNDCATCHER_DATA_HOME`` 覆盖（测试 / 切换库用，
   默认 ``Config.data_dir``）；模型与 UCS 语料始终复用默认 home（只读共享）。
"""

from __future__ import annotations

__all__ = ["app"]