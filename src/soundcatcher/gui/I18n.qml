pragma Singleton

// 界面文案国际化：默认中文，可切英文。
//
// 设计（2026-09-20 人类拍板）：
// - **按语言单选**，不再「英文（中文）」双写。中文态显示「语义」，英文态显示「Semantic」。
//   （知识库 AGENTS.md 的「UI 元素中英双语」规则面向文档，软件界面按语言切换更合理。）
// - 用 `property string` + 字串表对象，不用 Qt `.ts/.qm`。理由：本工程字串量小（~60 条）、
//   全是 QML 内联文案；`.ts` 流程要维护 lupdate 抽取 + lrelease 编译两步，收益不抵复杂度。
//   将来若字串量暴涨或要接翻译外包，再迁 `.qm`（工具链已确认可用）。
// - 缺翻译时**回退中文**（见 `t()`），保证不会出现空白界面。
//
// 用法（QML）：import "." → `text: I18n.t("btn.search")`
import QtQuick

QtObject {
    id: i18n

    // 语言：zh | en（默认 zh）
    property string lang: "zh"

    readonly property bool isZh: lang === "zh"

    // ---------- 字串表 ----------
    readonly property var _zh: ({
        // 窗口
        "app.title":            "SoundCatcher — 本地 AI 音效库",
        "app.subtitle":         "全离线音效库",
        "app.about":            "SoundCatcher",
        // 检索（B4 三模式归一：界面不再暴露模式选择，统一 hybrid）
        "search.placeholder":   "搜索音效 — 中文/英文均可，如：玻璃破碎，带回响的",
        "btn.search":           "搜索",
        // 侧栏统计
        "card.library":         "音效库",
        "card.files":           "个文件",
        "card.embedded":        "已嵌入",
        "card.failed":          "失败",
        // 扫描面板
        "scan.title":           "扫描目录",
        "scan.placeholder":     "目录，如 D:\\音效库",
        "btn.start":            "开始",
        "btn.stop":             "停止",
        "scan.hint":            "子进程独立写库，GUI 只读共存（WAL）",
        // 侧栏页签（较窄，用短文案，避免 320px 下被 ElideRight 截断）
        "side.ucs":             "UCS 分类",
        "side.history":         "历史",
        "side.favorites":       "收藏",
        // UCS 树
        "ucsTree.title":        "UCS 分类树",
        "btn.expand":           "展开",
        "btn.collapse":         "折叠",
        "btn.refresh":          "刷新",
        "ucsTree.noCorpus":     "未找到 UCS 语料 — 先运行 soundcatcher ucs init",
        "ucsTree.hint":         "点击叶子分类浏览 · 计数随 ucs tag 推进",
        "ucsTree.expandTip":    "展开全部 UCS 分类",
        "ucsTree.collapseTip":  "折叠全部分类",
        "ucsTree.refreshTip":   "重新加载分类与计数",
        "ucsTree.expandedAll":  "已展开全部 %1 个 UCS 分类",
        "ucsTree.collapsedAll": "已折叠全部分类",
        // 历史页
        "hist.title":           "搜索历史",
        "btn.save":             "保存",
        "btn.clear":            "清空",
        "saved.title":          "已保存，持久",
        "saved.count":          "%1 条",
        "recent.title":         "本会话 %1 条",
        // 收藏页
        "fav.title":            "收藏",
        "btn.import":           "导入",
        "btn.export":           "导出",
        "fav.empty":            "在结果行点 ☆ 收藏 · 持久化到 %APPDATA%\\SoundCatcher",
        "fav.importTip":        "从导出的 md / csv / m3u 或路径列表文件导入收藏",
        "fav.tipOn":            "收藏",
        "fav.tipOff":           "取消收藏",
        "fav.importTitle":      "导入收藏",
        // 结果区
        "results.title":        "结果",
        "results.empty":        "输入查询开始搜索",
        "results.noHit":        "无结果 — 换个说法试试",
        "results.hit":          "命中 %1 条",
        "results.browse":       "分类浏览 · %1 条",
        "results.browseEmpty":  "该分类暂无已打标文件",
        "btn.similar":          "相似",
        "btn.relabel":          "改标",
        "relabel.tip":          "人工修正 UCS 分类（写回 ucs_labels）",
        // 改标弹窗
        "relabel.title":        "改标 — %1",
        "relabel.desc":         "选择 UCS 子分类写回 ucs_labels（source=manual，替换该文件全部自动分类）",
        "relabel.searchPh":     "搜索 753 个 UCS 分类，中文/英文/CatID 均可…",
        "btn.cancel":           "取消",
        "btn.apply":            "确定",
        // 播放条
        "play.nothing":         "未选择",
        "play.waveHint":        "选择结果以预览波形",
        "play.vol":             "音量",
        // 拖拽
        "drop.hint":            "松开以「以声搜声」",
        "drop.folderHint":      "松开以扫描此文件夹并建库",
        "drop.badType":         "请拖入一个音频文件或文件夹",
        "drop.unsupported":     "不支持的文件类型：%1（请拖入音频文件）",
        "drop.searching":       "以声搜声：%1",
        // 拖入文件夹 → 扫描确认
        "scan.confirmTitle":    "扫描文件夹",
        "scan.confirmBody":     "扫描以下文件夹并加入音效库？\n\n%1\n\n扫描在后台子进程进行，不影响当前浏览。",
        "scan.confirmOk":       "开始扫描",
        // 状态
        "status.searching":     "搜索中…",
        "status.latency":       "查询耗时 %1 ms",
        "status.translated":    "中文 → %1",
        "status.fav.on":        "★ 已收藏：%1",
        "status.fav.off":       "☆ 已取消：%1",
        "status.savedSearch":   "已保存搜索：%1",
        "status.badFileId":     "该条目没有 fileId，无法改标",
        "status.noCatalog":     "UCS 语料未就绪（data/ucs/catalog.json）",
        "status.hit":           "命中 %1 条 · 延迟已记录",
        // 菜单栏
        "menu.file":            "文件",
        "menu.view":            "查看",
        "menu.library":         "音效库",
        "menu.settings":        "设置",
        "menu.help":            "帮助",
        "menu.openDataDir":     "打开数据目录",
        "menu.openExportDir":   "打开导出目录",
        "menu.exportFav":       "导出收藏夹…",
        "menu.quit":            "退出",
        "menu.showUcsTree":     "显示 UCS 分类树",
        "menu.sources":         "来源文件夹…",
        // 来源文件夹管理
        "src.title":            "来源文件夹",
        "src.desc":             "登记音效素材所在目录。扫描与增量更新按这些来源进行；本表只登记路径，不改动源文件。",
        "src.empty":            "尚未登记来源文件夹",
        "src.add":              "添加文件夹…",
        "src.addTitle":         "选择要登记的来源文件夹",
        "src.scan":             "扫描",
        "src.scanAll":          "扫描全部",
        "src.remove":           "移除",
        "menu.theme":           "主题",
        "menu.theme.light":     "亮色",
        "menu.theme.dark":      "暗色",
        "menu.theme.system":    "随系统",
        "menu.language":        "语言",
        "menu.paths":           "路径设置…",
        "menu.expandAll":       "展开全部分类",
        "menu.collapseAll":     "折叠全部分类",
        "menu.shortcuts":       "快捷键一览",
        "menu.about":           "关于 SoundCatcher",
        "menu.resetLayout":     "重置侧栏宽度",
        // 快捷键弹窗
        "sc.title":             "快捷键一览",
        "sc.close":             "关闭",
        // 关于
        "about.text":           "SoundCatcher\n本地优先、无付费墙的 AI 音效库管理工具\n\n语义搜索 · 以声搜声 · UCS 自动分类 · 波形预览\n全部离线运行，数据不出本机",
        "about.ok":             "好",
        // 主题/语言切换提示
        "status.theme":         "主题已切换：%1",
        "status.lang":          "界面语言已切换：%1",
        "status.sidebarReset":  "侧栏宽度已重置为 %1 px",
        // 路径设置
        "paths.title":          "路径设置",
        "paths.desc":           "这五条路径决定音效库数据、模型与导出的存放位置。改动会写入 settings.json，并在下次启动时生效。",
        "paths.custom":         "已自定义",
        "paths.envForced":      "环境变量强制",
        "paths.envForcedHint":  "该项由环境变量（SOUNDCATCHER_*）强制指定，界面无法修改。",
        "paths.open":           "打开",
        "paths.change":         "更改",
        "paths.editTitle":      "更改路径 — %1",
        "paths.current":        "当前",
        "paths.newPlaceholder": "新路径，留空 = 恢复默认",
        "paths.browse":         "浏览…",
        "paths.doMigrate":      "把旧目录里的数据搬到新路径（推荐）",
        "paths.noMigrateHint":  "未勾选迁移：只改配置，旧数据留在原处不动。",
        "paths.resetPreview":   "将恢复为工程默认路径。",
        "paths.restartHint":    "路径在启动时读取，需要重启 SoundCatcher 才会生效。",
        "paths.settingsFile":   "设置文件",
        "paths.footerHint":     "旧目录只会被搬空、不会被删除；确认新位置数据完整后再自行清理。",
        "btn.close":            "关闭",
        // 快捷键弹窗明细
        "sc.playPause":         "播放 / 暂停",
        "sc.seek":              "前后跳转 ±5 秒",
        "sc.focusSearch":       "焦点跳到搜索框",
        "sc.focusScan":         "焦点跳到扫描目录框",
        "sc.stopAndFocus":      "停止播放并回到搜索框",
        "sc.sideTabs":          "切换侧栏页签（UCS / 历史 / 收藏）",
        "sc.moveRow":           "结果列表上下移动",
        "sc.playRow":           "播放当前结果行",
        "sc.favRow":            "收藏 / 取消收藏当前行",
        "sc.similarRow":        "对当前行「以声搜声」",
        "sc.applyCat":          "确认所选 UCS 分类",
        "sc.resetSidebar":      "重置侧栏宽度为 320",
        // 关于
        "about.version":        "版本 %1",
        "about.dataAt":         "数据目录"
    })

    readonly property var _en: ({
        "app.title":            "SoundCatcher — Local AI Sound Library",
        "app.subtitle":         "Fully Offline Sound Library",
        "app.about":            "SoundCatcher",
        "search.placeholder":   "Search sounds — Chinese or English, e.g. glass breaking",
        "btn.search":           "Search",
        "card.library":         "Library",
        "card.files":           "files",
        "card.embedded":        "Embedded",
        "card.failed":          "Failed",
        "scan.title":           "Scan folder",
        "scan.placeholder":     "Folder, e.g. D:\\SoundLibrary",
        "btn.start":            "Start",
        "btn.stop":             "Stop",
        "scan.hint":            "Subprocess writes independently; GUI stays read-only (WAL)",
        "side.ucs":             "UCS",
        "side.history":         "History",
        "side.favorites":       "Favorites",
        "ucsTree.title":        "UCS Tree",
        "btn.expand":           "Expand",
        "btn.collapse":         "Collapse",
        "btn.refresh":          "Refresh",
        "ucsTree.noCorpus":     "UCS corpus not found — run soundcatcher ucs init",
        "ucsTree.hint":         "Click a leaf category to browse · counts follow ucs tag",
        "ucsTree.expandTip":    "Expand all UCS categories",
        "ucsTree.collapseTip":  "Collapse all categories",
        "ucsTree.refreshTip":   "Reload categories and counts",
        "ucsTree.expandedAll":  "Expanded all %1 UCS categories",
        "ucsTree.collapsedAll": "Collapsed all categories",
        "hist.title":           "Search History",
        "btn.save":             "Save",
        "btn.clear":            "Clear",
        "saved.title":          "Saved (persistent)",
        "saved.count":          "%1 items",
        "recent.title":         "This session: %1",
        "fav.title":            "Favorites",
        "btn.import":           "Import",
        "btn.export":           "Export",
        "fav.empty":            "Click ☆ on a result to favorite · stored in %APPDATA%\\SoundCatcher",
        "fav.importTip":        "Import favorites from md / csv / m3u or a plain path list",
        "fav.tipOn":            "Add to favorites",
        "fav.tipOff":           "Remove from favorites",
        "fav.importTitle":      "Import favorites",
        "results.title":        "Results",
        "results.empty":        "Type a query to start",
        "results.noHit":        "No results — try another wording",
        "results.hit":          "%1 hits",
        "results.browse":       "UCS browse · %1",
        "results.browseEmpty":  "No tagged files in this category",
        "btn.similar":          "Similar",
        "btn.relabel":          "Relabel",
        "relabel.tip":          "Manually correct the UCS category (writes ucs_labels)",
        "relabel.title":        "Relabel — %1",
        "relabel.desc":         "Pick a UCS subcategory to write back (source=manual, replaces all auto labels)",
        "relabel.searchPh":     "Search 753 UCS categories by name or CatID…",
        "btn.cancel":           "Cancel",
        "btn.apply":            "Apply",
        "play.nothing":         "Nothing selected",
        "play.waveHint":        "Select a result to preview waveform",
        "play.vol":             "Vol",
        "drop.hint":            "Drop to search by sound",
        "drop.folderHint":      "Drop to scan this folder into your library",
        "drop.badType":         "Drop an audio file or a folder",
        "drop.unsupported":     "Unsupported file type: %1 (drop an audio file)",
        "drop.searching":       "Search by sound: %1",
        "scan.confirmTitle":    "Scan folder",
        "scan.confirmBody":     "Scan the following folder into your sound library?\n\n%1\n\nScanning runs in a background subprocess and does not block browsing.",
        "scan.confirmOk":       "Start scan",
        "status.searching":     "Searching…",
        "status.latency":       "Query took %1 ms",
        "status.translated":    "Chinese → %1",
        "status.fav.on":        "★ Favorited: %1",
        "status.fav.off":       "☆ Unfavorited: %1",
        "status.savedSearch":   "Saved search: %1",
        "status.badFileId":     "This item has no fileId; cannot relabel",
        "status.noCatalog":     "UCS corpus not ready (data/ucs/catalog.json)",
        "status.hit":           "%1 hits · latency recorded",
        "menu.file":            "File",
        "menu.view":            "View",
        "menu.library":         "Library",
        "menu.settings":        "Settings",
        "menu.help":            "Help",
        "menu.openDataDir":     "Open data folder",
        "menu.openExportDir":   "Open export folder",
        "menu.exportFav":       "Export favorites…",
        "menu.quit":            "Quit",
        "menu.showUcsTree":     "Show UCS tree",
        "menu.sources":         "Source folders…",
        "src.title":            "Source folders",
        "src.desc":             "Folders that hold your sound assets. Scanning and incremental updates run over these sources; this list only records paths and never touches the source files.",
        "src.empty":            "No source folder registered yet",
        "src.add":              "Add folder…",
        "src.addTitle":         "Pick a folder to register as a source",
        "src.scan":             "Scan",
        "src.scanAll":          "Scan all",
        "src.remove":           "Remove",
        "menu.theme":           "Theme",
        "menu.theme.light":     "Light",
        "menu.theme.dark":      "Dark",
        "menu.theme.system":    "Follow system",
        "menu.language":        "Language",
        "menu.paths":           "Path settings…",
        "menu.expandAll":       "Expand all categories",
        "menu.collapseAll":     "Collapse all categories",
        "menu.shortcuts":       "Keyboard shortcuts",
        "menu.about":           "About SoundCatcher",
        "menu.resetLayout":     "Reset sidebar width",
        "sc.title":             "Keyboard shortcuts",
        "sc.close":             "Close",
        "about.text":           "SoundCatcher\nLocal-first, paywall-free AI sound library manager\n\nSemantic search · Search by sound · Auto UCS tagging · Waveform preview\nFully offline — your data never leaves this machine",
        "about.ok":             "OK",
        "status.theme":         "Theme switched: %1",
        "status.lang":          "Language switched: %1",
        "status.sidebarReset":  "Sidebar width reset to %1 px",
        "paths.title":          "Path settings",
        "paths.desc":           "These five paths decide where library data, models and exports live. Changes are written to settings.json and take effect on the next launch.",
        "paths.custom":         "Custom",
        "paths.envForced":      "Env override",
        "paths.envForcedHint":  "This path is forced by an environment variable (SOUNDCATCHER_*); the UI cannot change it.",
        "paths.open":           "Open",
        "paths.change":         "Change",
        "paths.editTitle":      "Change path — %1",
        "paths.current":        "Current",
        "paths.newPlaceholder": "New path; leave empty to restore the default",
        "paths.browse":         "Browse…",
        "paths.doMigrate":      "Move existing data to the new path (recommended)",
        "paths.noMigrateHint":  "Migration off: only the setting changes; old data stays where it is.",
        "paths.resetPreview":   "Will restore the project default path.",
        "paths.restartHint":    "Paths are read at startup; restart SoundCatcher for the change to take effect.",
        "paths.settingsFile":   "Settings file",
        "paths.footerHint":     "The old folder is only emptied, never deleted — clean it up yourself once you've verified the new location.",
        "btn.close":            "Close",
        "sc.playPause":         "Play / pause",
        "sc.seek":              "Seek ±5 seconds",
        "sc.focusSearch":       "Focus the search box",
        "sc.focusScan":         "Focus the scan-folder box",
        "sc.stopAndFocus":      "Stop playback, back to search box",
        "sc.sideTabs":          "Switch sidebar tab (UCS / History / Favorites)",
        "sc.moveRow":           "Move up/down in results",
        "sc.playRow":           "Play the current result row",
        "sc.favRow":            "Toggle favorite on the current row",
        "sc.similarRow":        "Search by sound using the current row",
        "sc.applyCat":          "Confirm the selected UCS category",
        "sc.resetSidebar":      "Reset sidebar width to 320",
        "about.version":        "Version %1",
        "about.dataAt":         "Data folder"
    })

    /// 取文案；`args` 依次替换 %1 %2 …；缺 key 回退中文，再缺回退 key 本身。
    function t(key, ...args) {
        var table = isZh ? _zh : _en
        var s = table[key]
        if (s === undefined) s = _zh[key]
        if (s === undefined) return key
        for (var i = 0; i < args.length; i++) {
            s = s.replace("%" + (i + 1), args[i])
        }
        return s
    }

    /// 主题/语言切换的显示名（状态栏提示用）
    function themeName(mode) {
        if (mode === "light") return t("menu.theme.light")
        if (mode === "dark") return t("menu.theme.dark")
        return t("menu.theme.system")
    }

    function langName() {
        return isZh ? "中文" : "English"
    }

    function setLang(l) {
        if (l === "zh" || l === "en") lang = l
    }
}
