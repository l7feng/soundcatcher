import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

ApplicationWindow {
    id: root
    width: 1380
    height: 880
    minimumWidth: 1000
    minimumHeight: 640
    visible: true
    color: Theme.bg
    title: I18n.t("app.title")

    // ---------- 主题色板（集中在 Theme.qml，此处只做别名）----------
    // 保留 cXxx 短别名：既让既有 300+ 处绑定零改动，也避免以后新增控件
    // 又要记一套新名字。**禁止再写颜色字面量** —— 亮/暗切换会漏掉硬编码色。
    // 注意：这里**必须用 property color 绑定**，不能用 `property alias` ——
    // QML 不允许 alias 指向单例（实测报 `Invalid alias reference. Unable to
    // find id "Theme"` 致使整份 main.qml 加载失败）。绑定同样能随 Theme 热切换。
    readonly property color cBg: Theme.bg
    readonly property color cPanel: Theme.panel
    readonly property color cPanel2: Theme.panel2
    readonly property color cLine: Theme.line
    readonly property color cText: Theme.text
    readonly property color cTextDim: Theme.textDim
    readonly property color cAccent: Theme.accent
    readonly property color cAccentDark: Theme.accentDark
    readonly property color cGreen: Theme.green
    readonly property color cOrange: Theme.orange
    readonly property color cRed: Theme.red
    readonly property color cRowHover: Theme.rowHover
    readonly property color cRowSel: Theme.rowSel
    readonly property color cOnColor: Theme.onColor

    // ---------- 状态 ----------
    property int libTotal: 0
    property int libEmbedded: 0
    property int libFailed: 0
    property string statusNote: ""
    property string ucsHint: ""
    property int hitCount: 0            // 上次查询命中数（结果区标题显示）
    property string lastLatencyMs: ""   // 上次查询耗时 ms（空 = 未查过）
    property string translationHint: "" // 「中文 → 英文」提示（不覆盖 statusNote）
    property var favPaths: []          // 已收藏的路径列表（收藏按钮状态用）
    property var savedList: []         // 已保存搜索（持久）
    property var catalogList: []       // UCS 扁平 753 类（改标弹窗用）
    // 任一文本输入框聚焦时，禁用会吞字符的全局快捷键（空格等）
    property bool anyInputFocus: searchField.activeFocus || scanDirField.activeFocus || catSearchField.activeFocus

    function fmtMs(ms) {
        if (ms < 0) return "0:00"
        var s = Math.floor(ms / 1000)
        return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0")
    }

    // -------- 改标：打开分类选择弹窗 + 搜索过滤 --------
    function openRelabel(fileId, filename) {
        if (!fileId || fileId <= 0) { showStatus(I18n.t("status.badFileId")); return }
        if (catalogList.length === 0) { showStatus(I18n.t("status.noCatalog")); return }
        relabelPopup.targetFileId = fileId
        relabelPopup.targetName = filename
        catSearchField.text = ""
        filterCats("")
        relabelPopup.open()
    }
    function filterCats(q) {
        q = (q || "").trim().toLowerCase()
        catModel.clear()
        var all = catalogList
        for (var i = 0; i < all.length; i++) {
            var it = all[i]
            var hit = q.length === 0
            if (!hit) {
                hit = (String(it.title || "").toLowerCase().indexOf(q) >= 0
                       || String(it.catid || "").toLowerCase().indexOf(q) >= 0
                       || String(it.category_zh || "").indexOf(q) >= 0
                       || String(it.subcategory_zh || "").indexOf(q) >= 0)
            }
            if (hit) catModel.append({ catid: it.catid, title: it.title })
        }
        catList.currentIndex = catModel.count > 0 ? 0 : -1
    }
    function doRelabel(catid) {
        var msg = backend.setUcsLabel(relabelPopup.targetFileId, catid)
        showStatus(msg)
        relabelPopup.close()
    }
    function chooseImportFile(url) {
        showStatus(backend.importFavorites(urlToPath(url)))
    }
    // file://C:/x/y.wav → C:/x/y.wav；file:///C:/x/y.wav → C:/x/y.wav
    function urlToPath(url) {
        var p = String(url)
        if (p.indexOf("file://") === 0) p = p.slice(7)
        if (p.indexOf("/") === 0) p = p.slice(1)
        return decodeURIComponent(p)
    }
    // -------- 拖入参考音频 → 以声搜声 --------
    function similarFromDrop(drop) {
        if (!drop.hasUrls || drop.urls.length === 0) {
            showStatus(I18n.t("drop.badType"))
            return
        }
        var p = urlToPath(drop.urls[0])
        var ext = p.slice(p.lastIndexOf(".") + 1).toLowerCase()
        if (["wav","aif","aiff","flac","mp3","m4a","ogg","opus","caf","rf64","wma","aac"].indexOf(ext) < 0) {
            showStatus(I18n.t("drop.unsupported", ext))
            return
        }
        dragHint.visible = false
        backend.doSimilar(p, 60)
        showStatus(I18n.t("drop.searching", p.slice(p.lastIndexOf("/") + 1)))
    }

    // -------- 键盘导航：结果列表当前行动作（供 Keys/快捷键复用） --------
    function playCurrentRow() {
        if (resultView.currentIndex < 0 || resultView.currentIndex >= resultsModel.count) return
        var it = resultsModel.get(resultView.currentIndex)
        backend.playFile(it.path, it.filename)
        backend.loadWaveform(it.fileId, it.path)
    }
    function toggleFavCurrentRow() {
        if (resultView.currentIndex < 0 || resultView.currentIndex >= resultsModel.count) return
        var it = resultsModel.get(resultView.currentIndex)
        backend.toggleFavorite(it.path, it.filename, it.fileId)
        statusNote = backend.isFavorite(it.path)
            ? I18n.t("status.fav.on", it.filename)
            : I18n.t("status.fav.off", it.filename)
    }
    function similarCurrentRow() {
        if (resultView.currentIndex < 0 || resultView.currentIndex >= resultsModel.count) return
        backend.doSimilar(resultsModel.get(resultView.currentIndex).path, 60)
    }

    // -------- UCS 分类树：展开 / 折叠全部 --------
    // 打开时默认展开前 3 个分类（原先），现提供全展开入口 —— 82 个根手动点开太费事
    function expandAllUcs() {
        var n = backend.ucsModelCount
        for (var r = 0; r < n; r++) ucsTreeView.expand(ucsTreeView.index(r, 0))
        statusNote = I18n.t("ucsTree.expandedAll", n)
    }
    function collapseAllUcs() {
        var n = backend.ucsModelCount
        for (var r = 0; r < n; r++) ucsTreeView.collapse(ucsTreeView.index(r, 0))
        statusNote = I18n.t("ucsTree.collapsedAll")
    }

    // 侧栏宽度复位到默认 320（菜单项 + 双击分隔条共用）
    function resetSidebarWidth() {
        backend.setSidebarWidth(320)
        sidebar.SplitView.preferredWidth = 320
        showStatus(I18n.t("status.sidebarReset", 320))
    }

    // ---------- 自动化探针挂钩（tests/theme_probe.py 用） ----------
    // QML 函数带参数时，从 Python 的 invokeMethod 调用不可靠（元对象里没有匹配的
    // slot 签名）。所以这里提供**无参**中转函数：探针只调它，参数由探针先写进
    // `probeArgs`。生产代码不受影响（不调用即无副作用）。
    property var probeArgs: []
    function probeApply() {
        var mode = probeArgs.length > 0 ? probeArgs[0] : "dark"
        var lang = probeArgs.length > 1 ? probeArgs[1] : "zh"
        applyTheme(mode)
        applyLanguage(lang)
        // 读回真实生效值，供探针断言（比猜内部状态可靠）
        probeResult = ({
            themeMode: Theme.mode,
            isDark: Theme.isDark,
            lang: I18n.lang,
            title: title,
            bg: String(Theme.bg),
            onColor: String(Theme.onColor),
            sidebarWidth: sidebar.width,
            treeHeight: ucsTreeView.height
        })
    }
    property var probeResult: ({})

    // 分类搜索探针：同上，无参中转。probeQuery 先写入，再调 probeFilterCats()，
    // 命中数回填 probeHitCount。用于验证改标弹窗的搜索式分类选择器。
    property string probeQuery: ""
    property int probeHitCount: 0
    function probeFilterCats() {
        filterCats(probeQuery)
        probeHitCount = catModel.count
    }

    function currentMode() {
        if (modeSemantic.checked) return "semantic"
        if (modeKeyword.checked) return "keyword"
        return "hybrid"
    }

    function doSearch() {
        var q = searchField.text.trim()
        if (q.length === 0) return
        resultsModel.clear()
        hitCount = 0
        lastLatencyMs = ""
        translationHint = ""     // 换新查询就清掉上一条的附注，避免张冠李戴
        backend.doSearch(q, currentMode(), 60)
        addHistory(q, currentMode())
    }

    function addHistory(q, mode) {
        for (var i = 0; i < historyModel.count; i++) {
            if (historyModel.get(i).q === q) { historyModel.remove(i); break }
        }
        historyModel.insert(0, { q: q, mode: mode })
        while (historyModel.count > 30) historyModel.remove(historyModel.count - 1)
    }

    function showStatus(msg) {
        statusNote = msg
    }

    // ---------- 后端信号 ----------
    Connections {
        target: backend
        function onReady(ok, message) {
            showStatus(ok ? message : ("⚠ " + message))
            if (!ok) emptyText.text = message
        }
        function onSearchFinished(items) {
            resultsModel.clear()
            for (var i = 0; i < items.length; i++) resultsModel.append(items[i])
            hitCount = items.length
            statusNote = I18n.t("status.hit", items.length)
            emptyText.text = items.length === 0 ? I18n.t("results.noHit") : ""
        }
        function onSearchFailed(msg) {
            statusNote = "✗ " + msg
            emptyText.text = msg
        }
        function onTranslationNote(note) {
            // 只做「中文 → 英文」的附带提示：状态栏的主语义是「上次查询结果」，
            // 直接覆盖会把命中数顶掉。这里单独走一个小角标。
            translationHint = note
        }
        function onStatsChanged(total, embedded, failed) {
            libTotal = total; libEmbedded = embedded; libFailed = failed
        }
        function onQueryLatency(sec) {
            lastLatencyMs = (sec * 1000).toFixed(1)
        }
        function onWaveformReady(fileId, peaks) {
            waveCanvas.peaks = peaks
        }
        function onUcsTreeChanged() {
            ucsHint = backend.ucsModelCount === 0
                ? I18n.t("ucsTree.noCorpus")
                : I18n.t("ucsTree.hint")
            // 打开时展开前 3 个分类，方便第一眼看到结构
            // 注意：Qt 6.11 TreeView 用 index(row, column)，modelIndex() 已废弃
            var n = Math.min(3, backend.ucsModelCount)
            for (var r = 0; r < n; r++) {
                ucsTreeView.expand(ucsTreeView.index(r, 0))
            }
        }
        function onBrowseFinished(items) {
            resultsModel.clear()
            for (var i = 0; i < items.length; i++) resultsModel.append(items[i])
            statusNote = I18n.t("results.browse", items.length)
            emptyText.text = items.length === 0 ? I18n.t("results.browseEmpty") : ""
        }
        function onFavoritesChanged() {
            syncFavorites()
        }
        function onSavedSearchesChanged() {
            savedList = backend.savedSearches
            syncSaved()
        }
    }

    // 收藏状态同步到前端（结果行星标 + Favorites 页列表）
    function syncFavorites() {
        favPaths = []
        favoritesModel.clear()
        var fs = backend.favorites
        for (var i = 0; i < fs.length; i++) {
            var f = fs[i]
            favPaths.push(f.path)
            favoritesModel.append({ path: f.path, filename: f.filename || (f.path.split("/").pop().split("\\").pop()) })
        }
    }

    // 保存搜索同步到 History 页的 Saved 区块
    function syncSaved() {
        savedModel.clear()
        var ss = savedList
        for (var i = 0; i < ss.length; i++) savedModel.append({ q: ss[i].query, mode: ss[i].mode })
    }

    // 播放/进度轮询
    Timer {
        interval: 100
        running: true
        repeat: true
        onTriggered: {
            var d = backend.playbackDuration()
            timeLabel.text = fmtMs(backend.playbackPosition()) + " / " + fmtMs(d)
            waveCanvas.progress = d > 0 ? backend.playbackPosition() / d : 0
            playBtn.text = backend.isPlaying ? "⏸" : "▶"
            if (!posSlider.pressed) posSlider.value = backend.playbackPosition()
        }
    }

    // ---------- 键盘导航：全局快捷键 ----------
    // 空格播放/暂停（输入框聚焦或结果列表聚焦时让位：前者防吞字符，后者由
    // resultView 的 Keys 接管为"播放当前行"）
    Shortcut {
        sequence: "Space"
        enabled: !root.anyInputFocus && !resultView.activeFocus
        onActivated: backend.togglePlay()
    }
    Shortcut {
        sequence: "Ctrl+P"
        onActivated: backend.togglePlay()
    }
    // 左右跳转 ±5 秒（Ctrl 修饰避免与输入框光标冲突）
    Shortcut {
        sequence: "Ctrl+Left"
        onActivated: backend.seekTo(Math.max(0, backend.playbackPosition() - 5000))
    }
    Shortcut {
        sequence: "Ctrl+Right"
        onActivated: backend.seekTo(Math.min(backend.playbackDuration(), backend.playbackPosition() + 5000))
    }
    // 侧栏页签切换
    Shortcut {
        sequence: "Ctrl+1"
        onActivated: sideTabs.currentIndex = 0
    }
    Shortcut {
        sequence: "Ctrl+2"
        onActivated: sideTabs.currentIndex = 1
    }
    Shortcut {
        sequence: "Ctrl+3"
        onActivated: sideTabs.currentIndex = 2
    }
    // 停止播放 + 焦点回搜索框
    Shortcut {
        sequence: "Esc"
        enabled: !root.anyInputFocus
        onActivated: {
            backend.stopPlay()
            searchField.forceActiveFocus()
            searchField.selectAll()
        }
    }
    // 焦点直达扫描目录框
    Shortcut {
        sequence: "Ctrl+Shift+F"
        onActivated: scanDirField.forceActiveFocus()
    }

    // ---------- 菜单栏：文件 / 设置 / 帮助 ----------
    // 承载「主题三态切换 + 语言切换 + 路径设置」三个产品化入口。
    // QML MenuBar 挂在 ApplicationWindow 上会自动占顶部一条（不用手工布局）。
    menuBar: MenuBar {
        id: mainMenu
        font.pixelSize: 12

        // 自绘背景：默认样式在深色主题下与面板同色，看不出是一条 bar
        background: Rectangle {
            implicitHeight: 30
            color: cPanel
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: cLine }
        }
        delegate: MenuBarItem {
            id: mbi
            implicitHeight: 28
            contentItem: Label {
                text: mbi.text
                color: mbi.highlighted ? cOnColor : cText
                font.pixelSize: 12
                verticalAlignment: Text.AlignVCenter
            }
            background: Rectangle {
                radius: 4
                color: mbi.highlighted ? cAccent : "transparent"
            }
        }

        Menu {
            title: I18n.t("menu.file")
            delegate: root.menuItemDelegate
            MenuItem {
                text: I18n.t("menu.openDataDir")
                onTriggered: showStatus(backend.openDataFolder())
            }
            MenuItem {
                text: I18n.t("menu.openExportDir")
                onTriggered: showStatus(backend.openExportFolder())
            }
            MenuSeparator {}
            MenuItem {
                text: I18n.t("menu.exportFav")
                enabled: favoritesModel.count > 0
                onTriggered: showStatus(backend.exportFavorites("md"))
            }
            MenuSeparator {}
            MenuItem {
                text: I18n.t("menu.quit")
                onTriggered: Qt.quit()
            }
        }

        Menu {
            title: I18n.t("menu.settings")
            delegate: root.menuItemDelegate

            Menu {
                title: I18n.t("menu.theme")
                delegate: root.menuItemDelegate
                // 三态互斥；当前态打勾。不用 ActionGroup 是为了少一层间接
                MenuItem {
                    text: I18n.t("menu.theme.light")
                    checkable: true
                    checked: Theme.mode === "light"
                    onTriggered: root.applyTheme("light")
                }
                MenuItem {
                    text: I18n.t("menu.theme.dark")
                    checkable: true
                    checked: Theme.mode === "dark"
                    onTriggered: root.applyTheme("dark")
                }
                MenuItem {
                    text: I18n.t("menu.theme.system")
                    checkable: true
                    checked: Theme.mode === "system"
                    onTriggered: root.applyTheme("system")
                }
            }

            Menu {
                title: I18n.t("menu.language")
                delegate: root.menuItemDelegate
                MenuItem {
                    text: "中文"
                    checkable: true
                    checked: I18n.lang === "zh"
                    onTriggered: root.applyLanguage("zh")
                }
                MenuItem {
                    text: "English"
                    checkable: true
                    checked: I18n.lang === "en"
                    onTriggered: root.applyLanguage("en")
                }
            }

            MenuSeparator {}
            MenuItem {
                text: I18n.t("menu.paths")
                onTriggered: pathsDialog.open()
            }
            MenuSeparator {}
            MenuItem {
                text: I18n.t("menu.expandAll")
                onTriggered: root.expandAllUcs()
            }
            MenuItem {
                text: I18n.t("menu.collapseAll")
                onTriggered: root.collapseAllUcs()
            }
            MenuSeparator {}
            MenuItem {
                text: I18n.t("menu.resetLayout")
                onTriggered: root.resetSidebarWidth()
            }
        }

        Menu {
            title: I18n.t("menu.help")
            delegate: root.menuItemDelegate
            MenuItem {
                text: I18n.t("menu.shortcuts")
                onTriggered: shortcutsDialog.open()
            }
            MenuItem {
                text: I18n.t("menu.about")
                onTriggered: aboutDialog.open()
            }
        }
    }

    // 菜单项统一样式（暗/亮主题下都要可读；默认样式在深色主题里文字是深色）
    readonly property Component menuItemDelegate: MenuItem {
        implicitHeight: 28
        contentItem: Label {
            text: parent.text
            color: cText
            font.pixelSize: 12
            leftPadding: 8
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            color: parent.highlighted ? cAccent : "transparent"
        }
        arrow: Label {
            text: "›"
            color: cTextDim
            font.pixelSize: 13
            x: parent.width - 18
            y: (parent.height - height) / 2
            visible: parent.subMenu !== null
        }
        indicator: Label {
            text: parent.checked ? "✓" : ""
            color: cAccent
            font.pixelSize: 12
            x: 2
            y: (parent.height - height) / 2
        }
    }

    // ---------- 主题 / 语言切换（热生效 + 持久化）----------
    function applyTheme(mode) {
        backend.setTheme(mode)
        Theme.setMode(mode)
        showStatus(I18n.t("status.theme", I18n.themeName(mode)))
    }
    function applyLanguage(lang) {
        backend.setLanguage(lang)
        I18n.setLang(lang)
        showStatus(I18n.t("status.lang", I18n.langName()))
    }

    // ---------- 顶层布局 ----------
    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        anchors.margins: 0

        // ================= 顶部工具条 =================
        Rectangle {
            id: toolbar
            Layout.fillWidth: true
            Layout.preferredHeight: 68
            color: cPanel
            border.color: cLine
            border.width: 1

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                spacing: 10

                // 应用名
                ColumnLayout {
                    spacing: 1
                    Layout.maximumWidth: 210
                    Label {
                        text: I18n.t("app.about")
                        color: cText
                        font.pixelSize: 18
                        font.bold: true
                    }
                    Label {
                        text: I18n.t("app.subtitle")
                        color: cTextDim
                        font.pixelSize: 11
                    }
                }

                // 模式切换（checkable 三选一：Semantic / Keyword / Hybrid）
                // 自定义 background + contentItem 以适配暗色主题（默认样式的文字为深色，在深底上不可见）
                ButtonGroup { id: modeGroup }
                Button {
                    id: modeSemantic
                    text: I18n.t("mode.semantic")
                    checkable: true
                    checked: true
                    ButtonGroup.group: modeGroup
                    property string mode: "semantic"
                    implicitHeight: 30
                    background: Rectangle {
                        radius: 6
                        color: modeSemantic.checked ? cAccent
                             : (modeSemantic.hovered ? cPanel2 : cPanel)
                        border.color: modeSemantic.checked ? cAccent : cLine
                        border.width: 1
                    }
                    contentItem: Label {
                        text: modeSemantic.text
                        color: modeSemantic.checked ? cOnColor : cText
                        font.pixelSize: 11
                        font.bold: modeSemantic.checked
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                Button {
                    id: modeKeyword
                    text: I18n.t("mode.keyword")
                    checkable: true
                    ButtonGroup.group: modeGroup
                    property string mode: "keyword"
                    implicitHeight: 30
                    background: Rectangle {
                        radius: 6
                        color: modeKeyword.checked ? cAccent
                             : (modeKeyword.hovered ? cPanel2 : cPanel)
                        border.color: modeKeyword.checked ? cAccent : cLine
                        border.width: 1
                    }
                    contentItem: Label {
                        text: modeKeyword.text
                        color: modeKeyword.checked ? cOnColor : cText
                        font.pixelSize: 11
                        font.bold: modeKeyword.checked
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                Button {
                    id: modeHybrid
                    text: I18n.t("mode.hybrid")
                    checkable: true
                    ButtonGroup.group: modeGroup
                    property string mode: "hybrid"
                    implicitHeight: 30
                    background: Rectangle {
                        radius: 6
                        color: modeHybrid.checked ? cAccent
                             : (modeHybrid.hovered ? cPanel2 : cPanel)
                        border.color: modeHybrid.checked ? cAccent : cLine
                        border.width: 1
                    }
                    contentItem: Label {
                        text: modeHybrid.text
                        color: modeHybrid.checked ? cOnColor : cText
                        font.pixelSize: 11
                        font.bold: modeHybrid.checked
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }

                // 搜索框
                TextField {
                    id: searchField
                    Layout.fillWidth: true
                    Layout.minimumWidth: 240
                    placeholderText: I18n.t("search.placeholder")
                    color: cText
                    placeholderTextColor: cTextDim
                    selectByMouse: true
                    onAccepted: root.doSearch()
                    background: Rectangle {
                        radius: 8
                        color: cBg
                        border.color: searchField.activeFocus ? cAccent : cLine
                        border.width: searchField.activeFocus ? 2 : 1
                    }
                }
                Shortcut {
                    sequence: "Ctrl+F"
                    onActivated: {
                        searchField.forceActiveFocus()
                        searchField.selectAll()
                    }
                }

                // 搜索按钮
                Button {
                    id: searchBtn
                    text: I18n.t("btn.search")
                    enabled: searchField.text.trim().length > 0
                    onClicked: root.doSearch()
                    background: Rectangle {
                        radius: 8
                        color: searchBtn.enabled ? cAccent : cPanel2
                        border.color: cAccent
                    }
                    contentItem: Label {
                        text: searchBtn.text
                        color: searchBtn.enabled ? cOnColor : cTextDim
                        font.bold: true
                    }
                }
            }
        }

        // ================= 主体 =================
        // SplitView 而非 RowLayout：侧栏与结果区之间的分隔条可拖拽调宽（用户要求）。
        // 宽度持久化到 settings.json（backend.sidebarWidth），下次启动恢复。
        //
        // ⚠️ Qt 6.11 的 SplitView（QQuickSplitView）**没有 leftWidth / rightWidth 属性**，
        // 也不暴露「子项当前宽度」。可写入口只有附加属性
        // SplitView.preferredWidth / minimumWidth / maximumWidth（见
        // QtQuick/Templates/plugins.qmltypes 的 QQuickSplitViewAttached）。
        // 因此这里：
        //   ① 用 sidebar.preferredWidth 绑定 backend.sidebarWidth 做初值；
        //   ② 用 sidebar.width（拖拽后被 SplitView 重写）读回当前宽度并持久化。
        SplitView {
            id: sideSplit
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            handle: Rectangle {
                implicitWidth: 5
                implicitHeight: 5
                color: SplitHandle.pressed ? cAccent
                     : (SplitHandle.hovered ? cAccentDark : "transparent")
                // 细到手感不好找 → 悬停时给一条可见的竖线
                Rectangle {
                    anchors.centerIn: parent
                    width: 1
                    height: parent.height
                    color: SplitHandle.hovered || SplitHandle.pressed ? cAccent : cLine
                }
                // 双击分隔条 = 重置为默认 320（和菜单「重置侧栏宽度」同义）
                TapHandler {
                    onDoubleTapped: root.resetSidebarWidth()
                }
            }

            // ---------- 左侧栏 ----------
            Rectangle {
                id: sidebar
                objectName: "sidebar"
                SplitView.preferredWidth: backend.sidebarWidth
                SplitView.minimumWidth: 260
                SplitView.maximumWidth: 640
                Layout.fillHeight: true
                color: cPanel
                border.color: cLine
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 8

                    // 库统计卡片
                    // 注意：Rectangle 无 implicitHeight，内部又用 anchors.fill → 必须显式给高度，
                    // 否则在 ColumnLayout 中塌缩为 0，内容会溢出并"透视"到下方页签上（实测踩中）
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 134
                        radius: 10
                        color: cPanel2
                        border.color: cLine
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 4
                            Label {
                                text: I18n.t("card.library")
                                color: cTextDim
                                font.pixelSize: 11
                            }
                            Label {
                                text: root.libTotal + " " + I18n.t("card.files")
                                color: cText
                                font.pixelSize: 16
                                font.bold: true
                            }
                            // 侧栏窄（236~264px），横向并排两行一定被截断
                            // → 改成上/下两行，各自独占整行宽度
                            Label {
                                text: I18n.t("card.embedded") + ": " + root.libEmbedded
                                color: cGreen
                                font.pixelSize: 11
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            Label {
                                text: I18n.t("card.failed") + ": " + root.libFailed
                                color: root.libFailed > 0 ? cRed : cTextDim
                                font.pixelSize: 11
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                        }
                    }

                    // ===== 后台扫描小面板 =====
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 104
                        radius: 10
                        color: cPanel2
                        border.color: cLine
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 5
                            Label {
                                text: I18n.t("scan.title")
                                color: cTextDim
                                font.pixelSize: 11
                            }
                            RowLayout {
                                spacing: 6
                                TextField {
                                    id: scanDirField
                                    Layout.fillWidth: true
                                    placeholderText: I18n.t("scan.placeholder")
                                    color: cText
                                    placeholderTextColor: cTextDim
                                    selectByMouse: true
                                    enabled: backend.scanState !== "running"
                                    onAccepted: showStatus(backend.startScan(text))
                                    background: Rectangle {
                                        radius: 6
                                        color: cBg
                                        border.color: scanDirField.activeFocus ? cAccent : cLine
                                        border.width: scanDirField.activeFocus ? 2 : 1
                                    }
                                }
                                Button {
                                    text: backend.scanState === "running" ? I18n.t("btn.stop") : I18n.t("btn.start")
                                    implicitWidth: 92
                                    onClicked: {
                                        showStatus(backend.scanState === "running"
                                                   ? backend.stopScan()
                                                   : backend.startScan(scanDirField.text))
                                    }
                                    background: Rectangle {
                                        radius: 7
                                        color: backend.scanState === "running"
                                              ? (parent.hovered ? cRed : Theme.dangerBg)
                                              : (parent.hovered ? cAccentDark : cPanel)
                                        border.color: backend.scanState === "running" ? cRed : cLine
                                    }
                                    contentItem: Label {
                                        text: parent.text
                                        color: parent.hovered ? cOnColor : cText
                                        font.pixelSize: 11
                                    }
                                }
                            }
                            Label {
                                text: backend.scanState === "running"
                                      ? "◉ " + backend.scanMessage
                                      : (backend.scanMessage.length > 0
                                         ? backend.scanMessage
                                         : I18n.t("scan.hint"))
                                color: backend.scanState === "running" ? cGreen
                                     : (backend.scanState === "failed" ? cRed : cTextDim)
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                                Layout.maximumHeight: 30
                                clip: true
                            }
                        }
                    }

                    // ===== 侧栏导航：UCS 分类 / 历史 / 收藏 =====
                    // ⚠️ 宽度不能用 `sideTabs.width` 反推：TabBar 的 implicitWidth 是由
                    // 子项 width 聚合出来的，子项又绑定 sideTabs.width → 双向依赖，
                    // Qt 会报 "Binding loop detected for property implicitWidth"。
                    // 改绑 **父容器（ColumnLayout）的 width**，它由 Layout 单向给出，不再成环。
                    TabBar {
                        id: sideTabs
                        objectName: "sideTabs"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34
                        spacing: 2
                        background: Rectangle {
                            color: "transparent"
                        }
                        // 按文案长度按比例分配宽度（等分会把最长的 Favorites 截断）。
                        // 比例 = 各自文案长度 + 最小内边距，保证三条都完整显示。
                        readonly property real _wUcs: 8
                        readonly property real _wHis: 12
                        readonly property real _wFav: 14
                        readonly property real _wSum: _wUcs + _wHis + _wFav
                        readonly property real _avail: parent.width - spacing * 2
                        TabButton {
                            id: tabUcs
                            text: I18n.t("side.ucs")
                            width: sideTabs._avail * sideTabs._wUcs / sideTabs._wSum
                            background: Rectangle {
                                radius: 6
                                color: tabUcs.checked ? cAccent : (tabUcs.hovered ? cPanel2 : cPanel)
                                border.color: tabUcs.checked ? cAccent : cLine
                                border.width: 1
                            }
                            contentItem: Label {
                                text: tabUcs.text
                                color: tabUcs.checked ? cOnColor : cText
                                font.pixelSize: 11
                                font.bold: tabUcs.checked
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideNone
                            }
                        }
                        TabButton {
                            id: tabHistory
                            text: I18n.t("side.history")
                            width: sideTabs._avail * sideTabs._wHis / sideTabs._wSum
                            background: Rectangle {
                                radius: 6
                                color: tabHistory.checked ? cAccent : (tabHistory.hovered ? cPanel2 : cPanel)
                                border.color: tabHistory.checked ? cAccent : cLine
                                border.width: 1
                            }
                            contentItem: Label {
                                text: tabHistory.text
                                color: tabHistory.checked ? cOnColor : cText
                                font.pixelSize: 11
                                font.bold: tabHistory.checked
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideNone
                            }
                        }
                        TabButton {
                            id: tabFavorites
                            text: I18n.t("side.favorites")
                            width: sideTabs._avail * sideTabs._wFav / sideTabs._wSum
                            background: Rectangle {
                                radius: 6
                                color: tabFavorites.checked ? cAccent : (tabFavorites.hovered ? cPanel2 : cPanel)
                                border.color: tabFavorites.checked ? cAccent : cLine
                                border.width: 1
                            }
                            contentItem: Label {
                                text: tabFavorites.text
                                color: tabFavorites.checked ? cOnColor : cText
                                font.pixelSize: 11
                                font.bold: tabFavorites.checked
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideNone
                            }
                        }
                    }

                    StackLayout {
                        id: sideStack
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        currentIndex: sideTabs.currentIndex

                        // ---------- UCS 浏览树 ----------
                        Rectangle {
                            color: "transparent"
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.topMargin: 4
                                spacing: 5

                                RowLayout {
                                    spacing: 4
                                    Label {
                                        text: I18n.t("ucsTree.title")
                                        color: cTextDim
                                        font.pixelSize: 11
                                        font.bold: true
                                    }
                                    Item { Layout.fillWidth: true }
                                    Button {
                                        text: I18n.t("btn.expand")
                                        implicitHeight: 22
                                        implicitWidth: 40
                                        onClicked: root.expandAllUcs()
                                        ToolTip.visible: hovered
                                        ToolTip.text: I18n.t("ucsTree.expandTip")
                                        background: Rectangle {
                                            radius: 6
                                            color: parent.hovered ? cAccentDark : cPanel2
                                            border.color: cLine
                                        }
                                        contentItem: Label {
                                            text: parent.text
                                            color: parent.hovered ? cOnColor : cTextDim
                                            font.pixelSize: 10
                                            horizontalAlignment: Text.AlignHCenter
                                            verticalAlignment: Text.AlignVCenter
                                        }
                                    }
                                    Button {
                                        text: I18n.t("btn.collapse")
                                        implicitHeight: 22
                                        implicitWidth: 40
                                        onClicked: root.collapseAllUcs()
                                        ToolTip.visible: hovered
                                        ToolTip.text: I18n.t("ucsTree.collapseTip")
                                        background: Rectangle {
                                            radius: 6
                                            color: parent.hovered ? cAccentDark : cPanel2
                                            border.color: cLine
                                        }
                                        contentItem: Label {
                                            text: parent.text
                                            color: parent.hovered ? cOnColor : cTextDim
                                            font.pixelSize: 10
                                            horizontalAlignment: Text.AlignHCenter
                                            verticalAlignment: Text.AlignVCenter
                                        }
                                    }
                                    Button {
                                        text: I18n.t("btn.refresh")
                                        implicitHeight: 22
                                        implicitWidth: 40
                                        onClicked: backend.refreshUcsTree()
                                        ToolTip.visible: hovered
                                        ToolTip.text: I18n.t("ucsTree.refreshTip")
                                        background: Rectangle {
                                            radius: 6
                                            color: parent.hovered ? cAccentDark : cPanel2
                                            border.color: cLine
                                        }
                                        contentItem: Label {
                                            text: parent.text
                                            color: parent.hovered ? cOnColor : cTextDim
                                            font.pixelSize: 10
                                            horizontalAlignment: Text.AlignHCenter
                                            verticalAlignment: Text.AlignVCenter
                                        }
                                    }
                                }
                                Label {
                                    text: ucsHint
                                    color: cTextDim
                                    font.pixelSize: 10
                                    wrapMode: Text.WordWrap
                                    visible: ucsHint.length > 0
                                }

                                TreeView {
                                    id: ucsTreeView
                                    objectName: "ucsTreeView"
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    clip: true
                                    model: backend.ucsModel
                                    delegate: TreeViewDelegate {
                                        id: td
                                        required property string tit
                                        required property int cnt
                                        required property string catid
                                        required property bool isleaf
                                        implicitHeight: 26
                                        implicitWidth: ucsTreeView.width
                                        text: (td.cnt > 0 ? td.cnt + " · " : "") + td.tit
                                        // 截断兜底：名称被 ElideRight 截掉时，悬停可读全名
                                        ToolTip.visible: hovered && truncated
                                        ToolTip.text: td.text
                                        // 暗色主题：默认文字色为深色，在深底上不可见 → 必须显式指定
                                        // 叶子（753 子类）用主文字色，分类用强调色区分层级
                                        contentItem: Label {
                                            id: tdLabel
                                            text: td.text
                                            color: td.isleaf ? cText : cAccent
                                            font.pixelSize: 11
                                            font.bold: !td.isleaf
                                            elide: Text.ElideRight
                                            verticalAlignment: Text.AlignVCenter
                                            leftPadding: td.depth * 11 + 4
                                            readonly property bool truncated:
                                                tdLabel.implicitWidth > tdLabel.width
                                        }
                                        background: Rectangle {
                                            color: td.hovered ? cRowHover : "transparent"
                                            radius: 4
                                        }
                                        // Qt 6.11 的 TreeView 基于 TableView，**没有 currentIndex**，
                                        // 只有 currentRow / currentColumn。原写 currentIndex 会抛
                                        // `Cannot assign to non-existent property "currentIndex"`，
                                        // 使整个 onClicked 处理器失效 → 点叶子不触发 browseUcs（2026-09-20 修正）
                                        onClicked: {
                                            ucsTreeView.currentRow = td.row
                                            if (isleaf) backend.browseUcs(catid)
                                        }
                                    }
                                }
                            }
                        }

                        // ---------- 搜索历史（持久保存 + 会话记录） ----------
                        Rectangle {
                            color: "transparent"
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.topMargin: 4
                                spacing: 5

                                RowLayout {
                                    Label {
                                        text: I18n.t("hist.title")
                                        color: cTextDim
                                        font.pixelSize: 11
                                        font.bold: true
                                    }
                                    Item { Layout.fillWidth: true }
                                    Button {
                                        text: I18n.t("btn.save")
                                        implicitHeight: 24
                                        enabled: searchField.text.trim().length > 0
                                        onClicked: {
                                            backend.saveSearch(searchField.text.trim(), currentMode())
                                            showStatus(I18n.t("status.savedSearch", searchField.text.trim()))
                                        }
                                        background: Rectangle {
                                            radius: 6
                                            color: parent.hovered ? cAccentDark : cPanel2
                                            border.color: cLine
                                        }
                                        contentItem: Label {
                                            text: parent.text
                                            color: parent.hovered ? cOnColor : cTextDim
                                            font.pixelSize: 11
                                        }
                                    }
                                    Button {
                                        text: I18n.t("btn.clear")
                                        implicitHeight: 24
                                        visible: historyModel.count > 0
                                        onClicked: historyModel.clear()
                                        background: Rectangle {
                                            radius: 6
                                            color: parent.hovered ? cRed : cPanel2
                                            border.color: cLine
                                        }
                                        contentItem: Label {
                                            text: parent.text
                                            color: parent.hovered ? cOnColor : cTextDim
                                            font.pixelSize: 11
                                        }
                                    }
                                }

                                // 已保存搜索（持久，%APPDATA%）
                                RowLayout {
                                    spacing: 6
                                    visible: savedModel.count > 0
                                    Label {
                                        text: I18n.t("saved.title")
                                        color: cGreen
                                        font.pixelSize: 10
                                        font.bold: true
                                    }
                                    Item { Layout.fillWidth: true }
                                    Label {
                                        text: I18n.t("saved.count", savedModel.count)
                                        color: cTextDim
                                        font.pixelSize: 10
                                    }
                                }
                                ListView {
                                    id: savedView
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: Math.min(132, savedModel.count * 30 + 4)
                                    visible: savedModel.count > 0
                                    clip: true
                                    spacing: 4
                                    activeFocusOnTab: true
                                    keyNavigationWraps: true
                                    model: ListModel { id: savedModel }
                                    // Enter 重跑已保存搜索
                                    Keys.onPressed: (event) => {
                                        if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && currentIndex >= 0) {
                                            searchField.text = savedModel.get(currentIndex).q
                                            searchField.forceActiveFocus()
                                            root.doSearch()
                                            event.accepted = true
                                        }
                                    }
                                    delegate: Rectangle {
                                        required property int index
                                        required property var model
                                        width: savedView.width
                                        height: 30
                                        radius: 6
                                        color: savedHover.hovered ? cRowHover : cPanel2
                                        border.color: cLine
                                        border.width: 1
                                        MouseArea {
                                            id: savedHover
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            onClicked: {
                                                searchField.text = savedModel.get(index).q
                                                searchField.forceActiveFocus()
                                                root.doSearch()
                                            }
                                        }
                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.leftMargin: 10
                                            anchors.rightMargin: 8
                                            spacing: 8
                                            Label {
                                                text: savedModel.get(index).q
                                                color: cText
                                                font.pixelSize: 12
                                                elide: Text.ElideRight
                                                Layout.fillWidth: true
                                            }
                                            Chip { text: savedModel.get(index).mode; tone: "green" }
                                            Button {
                                                text: "✕"
                                                implicitWidth: 22
                                                implicitHeight: 22
                                                onClicked: backend.removeSavedSearch(savedModel.get(index).q, savedModel.get(index).mode)
                                                background: Rectangle {
                                                    radius: 5
                                                    color: parent.hovered ? cRed : "transparent"
                                                }
                                                contentItem: Label {
                                                    text: parent.text
                                                    color: parent.hovered ? cOnColor : cTextDim
                                                    font.pixelSize: 10
                                                }
                                            }
                                        }
                                    }
                                }

                                Label {
                                    text: I18n.t("recent.title", historyModel.count)
                                    color: cTextDim
                                    font.pixelSize: 10
                                    font.bold: true
                                }

                                ListView {
                                    id: historyView
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    clip: true
                                    spacing: 4
                                    activeFocusOnTab: true
                                    keyNavigationWraps: true
                                    model: ListModel { id: historyModel }
                                    // Enter 重跑历史查询
                                    Keys.onPressed: (event) => {
                                        if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && currentIndex >= 0) {
                                            searchField.text = historyModel.get(currentIndex).q
                                            searchField.forceActiveFocus()
                                            root.doSearch()
                                            event.accepted = true
                                        }
                                    }
                                    delegate: Rectangle {
                                        required property int index
                                        required property var model
                                        width: historyView.width
                                        height: 30
                                        radius: 6
                                        color: histHover.hovered ? cRowHover : cPanel2
                                        border.color: cLine
                                        border.width: 1
                                        MouseArea {
                                            id: histHover
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            onClicked: {
                                                searchField.text = historyModel.get(index).q
                                                searchField.forceActiveFocus()
                                                root.doSearch()
                                            }
                                        }
                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.leftMargin: 10
                                            anchors.rightMargin: 8
                                            spacing: 8
                                            Label {
                                                text: historyModel.get(index).q
                                                color: cText
                                                font.pixelSize: 12
                                                elide: Text.ElideRight
                                                Layout.fillWidth: true
                                            }
                                            Chip { text: historyModel.get(index).mode; tone: "dim" }
                                        }
                                    }
                                }
                            }
                        }
                    // ---------- Favorites 收藏 ----------
                        Rectangle {
                            color: "transparent"
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.topMargin: 4
                                spacing: 5

                                RowLayout {
                                    Label {
                                        text: I18n.t("fav.title")
                                        color: cTextDim
                                        font.pixelSize: 11
                                        font.bold: true
                                    }
                                    Item { Layout.fillWidth: true }
                                    Label {
                                        text: favPaths.length + " 条"
                                        color: cTextDim
                                        font.pixelSize: 10
                                    }
                                    // 收藏夹导入：复用导出文件（md/csv/m3u）或纯路径列表
                                    Button {
                                        text: I18n.t("btn.import")
                                        implicitHeight: 24
                                        onClicked: importFavDialog.open()
                                        ToolTip.visible: hovered
                                        ToolTip.text: I18n.t("fav.importTip")
                                        background: Rectangle {
                                            radius: 6
                                            color: parent.hovered ? cAccentDark : cPanel2
                                            border.color: cLine
                                        }
                                        contentItem: Label {
                                            text: parent.text
                                            color: parent.hovered ? cOnColor : cTextDim
                                            font.pixelSize: 11
                                        }
                                    }
                                    // 收藏夹导出：格式 + 按钮
                                    ComboBox {
                                        id: exportFmtBox
                                        implicitWidth: 120
                                        implicitHeight: 24
                                        currentIndex: 0
                                        model: ["Markdown (.md)", "CSV (.csv)", "播放列表 (.m3u)", "Soundminer (.wavlist)"]
                                        font.pixelSize: 10
                                        palette.text: cText
                                        palette.buttonText: cText
                                        palette.button: cPanel2
                                        palette.base: cPanel2
                                        palette.highlight: cAccentDark
                                        palette.highlightedText: cOnColor
                                        background: Rectangle {
                                            radius: 6
                                            color: parent.hovered ? cAccentDark : cPanel2
                                            border.color: cLine
                                        }
                                        indicator: Label {
                                            x: exportFmtBox.width - 18
                                            y: exportFmtBox.height / 2 - 6
                                            text: "▾"
                                            color: exportFmtBox.hovered ? cOnColor : cTextDim
                                            font.pixelSize: 10
                                        }
                                        delegate: ItemDelegate {
                                            width: exportFmtBox.width
                                            implicitHeight: 26
                                            text: modelData
                                            font.pixelSize: 10
                                            highlighted: exportFmtBox.highlightedIndex === index
                                            background: Rectangle {
                                                radius: 4
                                                color: parent.highlighted ? cAccentDark : "transparent"
                                            }
                                            contentItem: Label {
                                                text: parent.text
                                                color: parent.highlighted ? cOnColor : cText
                                                font.pixelSize: 10
                                                leftPadding: 8
                                                verticalAlignment: Text.AlignVCenter
                                            }
                                        }
                                    }
                                    Button {
                                        text: I18n.t("btn.export")
                                        implicitHeight: 24
                                        enabled: favoritesModel.count > 0
                                        onClicked: {
                                            var fmts = ["md", "csv", "m3u", "wavlist"]
                                            showStatus(backend.exportFavorites(fmts[exportFmtBox.currentIndex]))
                                        }
                                        background: Rectangle {
                                            radius: 6
                                            color: parent.hovered ? cAccentDark : cPanel2
                                            border.color: cLine
                                        }
                                        contentItem: Label {
                                            text: parent.text
                                            color: parent.hovered ? cOnColor : cTextDim
                                            font.pixelSize: 11
                                        }
                                    }
                                }
                                Label {
                                    visible: favoritesModel.count === 0
                                    text: I18n.t("fav.empty")
                                    color: cTextDim
                                    font.pixelSize: 10
                                    wrapMode: Text.WordWrap
                                }

                                ListView {
                                    id: favoritesView
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    clip: true
                                    spacing: 4
                                    activeFocusOnTab: true
                                    keyNavigationWraps: true
                                    model: ListModel { id: favoritesModel }
                                    // Enter/空格 播放所选收藏
                                    Keys.onPressed: (event) => {
                                        if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) && currentIndex >= 0) {
                                            resultView.currentIndex = -1
                                            backend.playFile(favoritesModel.get(currentIndex).path, favoritesModel.get(currentIndex).filename)
                                            backend.loadWaveform(0, favoritesModel.get(currentIndex).path)
                                            event.accepted = true
                                        }
                                    }
                                    delegate: Rectangle {
                                        required property int index
                                        required property var model
                                        width: favoritesView.width
                                        height: 32
                                        radius: 6
                                        color: favHover.hovered ? cRowHover : cPanel2
                                        border.color: cLine
                                        border.width: 1
                                        MouseArea {
                                            id: favHover
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            onClicked: {
                                                resultView.currentIndex = -1
                                                backend.playFile(favoritesModel.get(index).path, favoritesModel.get(index).filename)
                                                backend.loadWaveform(0, favoritesModel.get(index).path)
                                            }
                                        }
                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.leftMargin: 10
                                            anchors.rightMargin: 8
                                            spacing: 8
                                            Label {
                                                text: favoritesModel.get(index).filename
                                                color: cText
                                                font.pixelSize: 12
                                                elide: Text.ElideMiddle
                                                Layout.fillWidth: true
                                            }
                                            Label {
                                                text: "▶"
                                                color: cTextDim
                                                font.pixelSize: 11
                                            }
                                            Button {
                                                text: "✕"
                                                implicitWidth: 22
                                                implicitHeight: 22
                                                onClicked: backend.removeFavorite(favoritesModel.get(index).path)
                                                background: Rectangle {
                                                    radius: 5
                                                    color: parent.hovered ? cRed : "transparent"
                                                }
                                                contentItem: Label {
                                                    text: parent.text
                                                    color: parent.hovered ? cOnColor : cTextDim
                                                    font.pixelSize: 10
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // 注意：此处**不能**放 `Item { Layout.fillHeight: true }`。
                    // 侧栏 ColumnLayout 里 StackLayout 已是 fillHeight 的主要消费者，
                    // 再插入一个弹性 Item 会与之平分剩余高度 —— 实测把树视口压到仅
                    // 105px（树只剩 3 行可见），而空白 Item 白占几百像素（2026-09-20 修）。

                    // 状态小字
                    // 优先级：搜索中提示 > 本次查询的「中文 → 英文」附注 > 常规状态
                    Label {
                        Layout.fillWidth: true
                        text: {
                            if (backend.searching) return I18n.t("status.searching")
                            if (root.translationHint !== "")
                                return I18n.t("status.translated", root.translationHint)
                            return root.statusNote
                        }
                        color: backend.searching ? cOrange : cTextDim
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                        Layout.maximumHeight: 48
                        clip: true
                    }
                }
            }

            // ---------- 中央结果列表 ----------
            Rectangle {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 420
                Layout.fillHeight: true
                color: cBg

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 8

                    // 结果统计行
                    RowLayout {
                        Label {
                            id: resultTitle
                            text: I18n.t("results.title")
                            color: cTextDim
                            font.pixelSize: 12
                            font.bold: true
                        }
                        // 命中条数 + 上次查询耗时（之前只算了不显示，白白浪费）
                        Label {
                            id: resultCount
                            visible: root.hitCount > 0
                            text: I18n.t("results.hit", root.hitCount)
                                  + (root.lastLatencyMs === ""
                                     ? "" : "  ·  " + I18n.t("status.latency", root.lastLatencyMs))
                            color: cTextDim
                            font.pixelSize: 11
                        }
                        Item { Layout.fillWidth: true }
                        BusyIndicator {
                            running: backend.searching
                            visible: backend.searching
                            implicitWidth: 18
                            implicitHeight: 18
                        }
                    }

                    ListView {
                        id: resultView
                        objectName: "resultView"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 6
                        model: ListModel { id: resultsModel }
                        currentIndex: -1
                        // 键盘导航：↑↓ 由 ListView 内置移动当前行；Enter/空格 播当前行；
                        // F 收藏切换；S 以声搜声；Esc 回搜索框
                        Keys.onPressed: (event) => {
                            if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
                                root.playCurrentRow(); event.accepted = true
                            } else if (event.key === Qt.Key_F) {
                                root.toggleFavCurrentRow(); event.accepted = true
                            } else if (event.key === Qt.Key_S) {
                                root.similarCurrentRow(); event.accepted = true
                            } else if (event.key === Qt.Key_Escape) {
                                resultView.focus = false
                                searchField.forceActiveFocus(); searchField.selectAll()
                                event.accepted = true
                            }
                        }
                        // 当前行变化时保证可见（配合高亮）
                        onCurrentIndexChanged: {
                            if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)
                        }

                        // 空状态 / 引导
                        Label {
                            id: emptyText
                            anchors.centerIn: parent
                            visible: resultsModel.count === 0
                            text: I18n.t("results.empty")
                            color: cTextDim
                            font.pixelSize: 14
                        }

                        delegate: Rectangle {
                            id: row
                            required property int index
                            required property var model
                            width: resultView.width
                            height: 66
                            radius: 10
                            color: resultView.currentIndex === index ? cRowSel
                                 : (rowHover.hovered ? cRowHover : cPanel)
                            border.color: cLine
                            border.width: 1

                            // 行点击层（在最底层：空白区点击选中+播放，按钮仍可点击）
                            MouseArea {
                                id: rowHover
                                anchors.fill: parent
                                hoverEnabled: true
                                onClicked: {
                                    resultView.currentIndex = index
                                    resultView.forceActiveFocus()
                                    backend.playFile(row.model.path, row.model.filename)
                                    backend.loadWaveform(row.model.fileId, row.model.path)
                                }
                            }

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 14
                                anchors.rightMargin: 10
                                anchors.topMargin: 8
                                anchors.bottomMargin: 8
                                spacing: 12

                                // 播放三角（当前项高亮）
                                Rectangle {
                                    Layout.preferredWidth: 26
                                    Layout.preferredHeight: 26
                                    radius: 13
                                    color: resultView.currentIndex === index ? cAccent : cPanel2
                                    Label {
                                        anchors.centerIn: parent
                                        text: "▶"
                                        color: resultView.currentIndex === index ? cOnColor : cTextDim
                                        font.pixelSize: 12
                                    }
                                }

                                ColumnLayout {
                                    spacing: 3
                                    Label {
                                        text: row.model.filename
                                        color: cText
                                        font.pixelSize: 14
                                        font.bold: true
                                        elide: Text.ElideMiddle
                                        Layout.preferredWidth: Math.max(160, row.width * 0.42)
                                    }
                                    RowLayout {
                                        spacing: 8
                                        Chip { text: row.model.durationStr; tone: "dim" }
                                        Chip { text: (row.model.score * 100).toFixed(1) + "%"; tone: "accent" }
                                        Chip { text: row.model.source; tone: "dim" }
                                        Label {
                                            text: row.model.parent
                                            color: cTextDim
                                            font.pixelSize: 11
                                            elide: Text.ElideMiddle
                                            Layout.maximumWidth: 220
                                        }
                                    }
                                    Row {
                                        spacing: 4
                                        Repeater {
                                            model: row.model.ucsTags
                                            Chip { text: modelData; tone: "green" }
                                        }
                                        Repeater {
                                            model: row.model.otherTags
                                            Chip { text: modelData; tone: "dim" }
                                        }
                                    }
                                }

                                Item { Layout.fillWidth: true }

                                // 收藏星标
                                Button {
                                    property bool fav: root.favPaths.indexOf(row.model.path) >= 0
                                    text: fav ? "★" : "☆"
                                    implicitWidth: 40
                                    implicitHeight: 32
                                    onClicked: {
                                        backend.toggleFavorite(row.model.path, row.model.filename, row.model.fileId)
                                    }
                                    ToolTip.visible: hovered
                                    ToolTip.text: fav ? I18n.t("fav.tipOff") : I18n.t("fav.tipOn")
                                    background: Rectangle {
                                        radius: 7
                                        color: parent.hovered ? cAccentDark : cPanel2
                                        border.color: cLine
                                    }
                                    contentItem: Label {
                                        text: parent.text
                                        color: parent.fav ? cOrange : cTextDim
                                        font.pixelSize: 15
                                    }
                                }

                                Button {
                                    text: I18n.t("btn.similar")
                                    onClicked: {
                                        backend.doSimilar(row.model.path, 60)
                                        resultView.currentIndex = index
                                    }
                                    background: Rectangle {
                                        radius: 7
                                        color: parent.hovered ? cAccentDark : cPanel2
                                        border.color: cLine
                                    }
                                    contentItem: Label {
                                        text: parent.text
                                        color: parent.hovered ? cOnColor : cText
                                        font.pixelSize: 12
                                    }
                                }

                                Button {
                                    text: I18n.t("btn.relabel")
                                    onClicked: {
                                        root.openRelabel(row.model.fileId, row.model.filename)
                                        resultView.currentIndex = index
                                    }
                                    ToolTip.visible: hovered
                                    ToolTip.text: I18n.t("relabel.tip")
                                    background: Rectangle {
                                        radius: 7
                                        color: parent.hovered ? Theme.relabelHover : cPanel2
                                        border.color: parent.hovered ? cGreen : cLine
                                    }
                                    contentItem: Label {
                                        text: parent.text
                                        color: parent.hovered ? cOnColor : cText
                                        font.pixelSize: 12
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // 拖拽结束后才写盘：拖拽过程中 sidebar.width 每帧都在变，
        // 逐帧写 settings.json 会打满磁盘 IO（且没必要）→ 停手 400ms 后再持久化。
        Timer {
            id: sidebarSaveTimer
            interval: 400
            repeat: false
            onTriggered: {
                // 只有用户真的改了宽度才写（避免启动时初值回写一次）
                if (Math.round(sidebar.width) !== backend.sidebarWidth)
                    backend.setSidebarWidth(Math.round(sidebar.width))
            }
        }
        Connections {
            target: sidebar
            function onWidthChanged() {
                if (sideSplit.resizing || Math.abs(Math.round(sidebar.width) - backend.sidebarWidth) >= 1)
                    sidebarSaveTimer.restart()
            }
        }

        // ================= 底部播放条 + 波形 =================
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 150
            color: cPanel
            border.color: cLine
            border.width: 1

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 6

                // 当前文件
                Label {
                    id: nowLabel
                    text: "（" + I18n.t("play.nothing") + "）"
                    color: cTextDim
                    font.pixelSize: 12
                    elide: Text.ElideMiddle
                }

                // 波形
                Canvas {
                    id: waveCanvas
                    Layout.fillWidth: true
                    Layout.preferredHeight: 72
                    property var peaks: []
                    property real progress: 0.0

                    function paintWave(ctx) {
                        var pts = waveCanvas.peaks || []
                        ctx.clearRect(0, 0, waveCanvas.width, waveCanvas.height)
                        ctx.fillStyle = Theme.canvasBg
                        ctx.fillRect(0, 0, waveCanvas.width, waveCanvas.height)
                        if (pts.length === 0) {
                            ctx.fillStyle = cTextDim
                            // Canvas 的 ctx.font 不受 QApplication 默认字体影响，
                            // 必须显式点名含 CJK 字形的族，否则中文靠系统 fallback（可能变方框）
                            ctx.font = "13px 'Microsoft YaHei UI','Microsoft YaHei','SimHei',sans-serif"
                            ctx.textAlign = "center"
                            ctx.fillText(I18n.t("play.waveHint"),
                                         waveCanvas.width / 2, waveCanvas.height / 2)
                            return
                        }
                        var mid = waveCanvas.height / 2
                        var step = waveCanvas.width / pts.length
                        ctx.strokeStyle = cAccent
                        ctx.lineWidth = 2
                        ctx.beginPath()
                        for (var i = 0; i < pts.length; i++) {
                            var x = i * step
                            var v = Math.max(0.03, Math.min(1, pts[i])) * (mid - 5)
                            ctx.moveTo(x, mid - v)
                            ctx.lineTo(x, mid + v)
                        }
                        ctx.stroke()
                        // 进度游标
                        ctx.fillStyle = cOrange
                        ctx.fillRect(waveCanvas.progress * waveCanvas.width - 1, 0, 2, waveCanvas.height)
                    }

                    onPaint: paintWave(getContext("2d"))
                    onWidthChanged: requestPaint()
                    onPeaksChanged: requestPaint()
                    onProgressChanged: requestPaint()
                }

                // 控制条
                RowLayout {
                    spacing: 10
                    Button {
                        id: playBtn
                        text: "▶"
                        font.pixelSize: 16
                        implicitWidth: 44
                        implicitHeight: 36
                        onClicked: backend.togglePlay()
                        background: Rectangle { radius: 8; color: parent.hovered ? cAccent : cPanel2; border.color: cLine }
                        contentItem: Label { text: parent.text; color: parent.hovered ? cOnColor : cText }
                    }
                    Slider {
                        id: posSlider
                        Layout.fillWidth: true
                        from: 0
                        to: Math.max(1, backend.playbackDuration())
                        onMoved: backend.seekTo(value)
                    }
                    Label {
                        id: timeLabel
                        text: "0:00 / 0:00"
                        color: cTextDim
                        font.pixelSize: 12
                        font.family: "Consolas"
                    }
                    Label { text: I18n.t("play.vol"); color: cTextDim; font.pixelSize: 11 }
                    Slider {
                        Layout.preferredWidth: 110
                        from: 0; to: 1
                        value: 0.8
                        onMoved: backend.setVolume(value)
                    }
                }
            }
        }
    }

    // ---------- 改标弹窗：UCS 分类选择（搜索过滤） ----------
    Popup {
        id: relabelPopup
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        x: Math.round((parent.width - width) / 2)
        y: Math.round((parent.height - height) / 2)
        width: 480
        height: Math.min(root.height - 140, 580)
        property int targetFileId: -1
        property string targetName: ""

        background: Rectangle {
            radius: 12
            color: cPanel
            border.color: cLine
            border.width: 1
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 8

            Label {
                text: I18n.t("relabel.title", relabelPopup.targetName)
                color: cText
                font.pixelSize: 14
                font.bold: true
                elide: Text.ElideMiddle
            }
            Label {
                text: I18n.t("relabel.desc")
                color: cTextDim
                font.pixelSize: 10
                wrapMode: Text.WordWrap
            }

            RowLayout {
                spacing: 6
                TextField {
                    id: catSearchField
                    Layout.fillWidth: true
                    placeholderText: I18n.t("relabel.searchPh")
                    color: cText
                    placeholderTextColor: cTextDim
                    selectByMouse: true
                    onTextChanged: root.filterCats(text)
                    background: Rectangle {
                        radius: 6
                        color: cBg
                        border.color: catSearchField.activeFocus ? cAccent : cLine
                        border.width: catSearchField.activeFocus ? 2 : 1
                    }
                }
                Button {
                    text: I18n.t("btn.clear")
                    implicitHeight: 28
                    enabled: catSearchField.text.length > 0
                    onClicked: catSearchField.text = ""
                    background: Rectangle {
                        radius: 6
                        color: parent.hovered ? cAccentDark : cPanel2
                        border.color: cLine
                    }
                    contentItem: Label {
                        text: parent.text
                        color: parent.hovered ? cOnColor : cTextDim
                        font.pixelSize: 11
                    }
                }
            }

            ListView {
                id: catList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 3
                model: ListModel { id: catModel }
                boundsBehavior: Flickable.StopAtBounds
                // Enter 确认当前分类
                Keys.onPressed: (event) => {
                    if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && catList.currentIndex >= 0) {
                        root.doRelabel(catModel.get(catList.currentIndex).catid)
                        event.accepted = true
                    }
                }
                delegate: Rectangle {
                    required property int index
                    required property var model
                    width: catList.width
                    height: 32
                    radius: 6
                    color: catList.currentIndex === index ? cRowSel : (catHover.hovered ? cRowHover : cPanel2)
                    border.color: cLine
                    border.width: 1
                    MouseArea {
                        id: catHover
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            catList.currentIndex = index
                            catList.forceActiveFocus()
                        }
                        onDoubleClicked: root.doRelabel(catModel.get(index).catid)
                    }
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 8
                        spacing: 8
                        Label {
                            text: catModel.get(index).title
                            color: cText
                            font.pixelSize: 12
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Chip {
                            text: catModel.get(index).catid
                            tone: "accent"
                            maxWidth: 150
                        }
                        Label {
                            text: "→"
                            color: cTextDim
                            font.pixelSize: 12
                        }
                    }
                }
            }

            RowLayout {
                Label {
                    text: catModel.count + " / 753"
                    color: cTextDim
                    font.pixelSize: 10
                }
                Item { Layout.fillWidth: true }
                Button {
                    text: I18n.t("btn.cancel")
                    implicitHeight: 28
                    onClicked: relabelPopup.close()
                    background: Rectangle {
                        radius: 6
                        color: parent.hovered ? cRed : cPanel2
                        border.color: cLine
                    }
                    contentItem: Label {
                        text: parent.text
                        color: parent.hovered ? cOnColor : cTextDim
                        font.pixelSize: 11
                    }
                }
                Button {
                    text: I18n.t("btn.apply")
                    implicitHeight: 28
                    enabled: catList.currentIndex >= 0
                    onClicked: root.doRelabel(catModel.get(catList.currentIndex).catid)
                    background: Rectangle {
                        radius: 6
                        color: parent.enabled ? (parent.hovered ? cAccent : Theme.applyBg) : cPanel2
                        border.color: parent.enabled ? cAccent : cLine
                    }
                    contentItem: Label {
                        text: parent.text
                        color: parent.enabled ? (parent.hovered ? cOnColor : cText) : cTextDim
                        font.pixelSize: 11
                    }
                }
            }
        }
    }

    // ---------- 路径设置对话框 ----------
    // 五条可改路径：查看当前生效值 / 更改 / 迁移旧数据。
    // 用户诉求原文：「输出的路径我想可以更改，可以在菜单栏设置。比如标签索引的
    // 路径。更改后直接把之前的移过去，然后是不是需要重启软件？然后把旧的删除」
    // → 迁移走 backend.setPath(migrate=true)；**不自动删旧目录**（只搬空留壳，
    //   让用户自己确认后处理，符合「不可逆操作先确认」的一贯原则）。
    Dialog {
        id: pathsDialog
        objectName: "pathsDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(760, root.width - 120)
        height: Math.min(640, root.height - 100)
        padding: 0

        property var rows: []
        property string restartNote: ""

        function reload() { rows = backend.pathInfo() }
        onOpened: { restartNote = ""; reload() }

        background: Rectangle {
            radius: 12
            color: cPanel
            border.color: cLine
            border.width: 1
        }

        header: Label {
            text: I18n.t("paths.title")
            color: cText
            font.pixelSize: 15
            font.bold: true
            leftPadding: 18
            topPadding: 14
        }

        contentItem: ColumnLayout {
            spacing: 8
            anchors.margins: 18

            Label {
                Layout.fillWidth: true
                text: I18n.t("paths.desc")
                color: cTextDim
                font.pixelSize: 10
                wrapMode: Text.WordWrap
            }

            ListView {
                id: pathList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 8
                model: ListModel { id: pathModel }

                function sync() {
                    pathModel.clear()
                    var rs = pathsDialog.rows
                    for (var i = 0; i < rs.length; i++) {
                        pathModel.append({
                            key: rs[i].key, desc: rs[i].desc, path: rs[i].path,
                            custom: rs[i].custom, envForced: rs[i].envForced
                        })
                    }
                }
                Connections {
                    target: pathsDialog
                    function onRowsChanged() { pathList.sync() }
                }
                Component.onCompleted: sync()

                delegate: Rectangle {
                    id: pathRow
                    required property int index
                    required property var model
                    width: pathList.width
                    height: 78
                    radius: 8
                    color: cPanel2
                    border.color: cLine
                    border.width: 1

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 5

                        RowLayout {
                            spacing: 6
                            Label {
                                text: pathRow.model.desc
                                color: cText
                                font.pixelSize: 12
                                font.bold: true
                                elide: Text.ElideRight
                                Layout.maximumWidth: 300
                            }
                            Chip {
                                visible: pathRow.model.custom
                                text: I18n.t("paths.custom")
                                tone: "green"
                            }
                            Chip {
                                visible: pathRow.model.envForced
                                text: I18n.t("paths.envForced")
                                tone: "accent"
                            }
                            Item { Layout.fillWidth: true }
                            Button {
                                text: I18n.t("paths.open")
                                implicitHeight: 24
                                implicitWidth: 64
                                onClicked: showStatus(backend.openFolder(pathRow.model.path))
                                background: Rectangle {
                                    radius: 6
                                    color: parent.hovered ? cAccentDark : cPanel
                                    border.color: cLine
                                }
                                contentItem: Label {
                                    text: parent.text
                                    color: parent.hovered ? cOnColor : cTextDim
                                    font.pixelSize: 10
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }
                            Button {
                                text: I18n.t("paths.change")
                                implicitHeight: 24
                                implicitWidth: 64
                                enabled: !pathRow.model.envForced
                                onClicked: {
                                    pathEditDialog.targetKey = pathRow.model.key
                                    pathEditDialog.targetDesc = pathRow.model.desc
                                    pathEditDialog.oldPath = pathRow.model.path
                                    pathEditDialog.newPath = pathRow.model.path
                                    pathEditDialog.open()
                                }
                                background: Rectangle {
                                    radius: 6
                                    color: !parent.enabled ? cPanel
                                         : (parent.hovered ? cAccent : cAccentDark)
                                    border.color: parent.enabled ? cAccent : cLine
                                }
                                contentItem: Label {
                                    text: parent.text
                                    color: parent.enabled
                                         ? (parent.hovered ? cOnColor : cText)
                                         : cTextDim
                                    font.pixelSize: 10
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            text: pathRow.model.envForced
                                  ? I18n.t("paths.envForcedHint")
                                  : pathRow.model.path
                            color: pathRow.model.envForced ? cOrange : cTextDim
                            font.pixelSize: 10
                            elide: Text.ElideMiddle
                            ToolTip.visible: hovered
                            ToolTip.text: pathRow.model.path
                        }
                    }
                }
            }

            Label {
                Layout.fillWidth: true
                visible: pathsDialog.restartNote.length > 0
                text: "⚠ " + pathsDialog.restartNote
                color: cOrange
                font.pixelSize: 11
                wrapMode: Text.WordWrap
            }

            Label {
                Layout.fillWidth: true
                text: I18n.t("paths.settingsFile") + "：" + backend.settingsFilePath()
                color: cTextDim
                font.pixelSize: 10
                elide: Text.ElideMiddle
            }
        }

        footer: RowLayout {
            spacing: 8
            anchors.margins: 18
            Label {
                Layout.fillWidth: true
                text: I18n.t("paths.footerHint")
                color: cTextDim
                font.pixelSize: 10
                wrapMode: Text.WordWrap
            }
            Button {
                text: I18n.t("btn.close")
                implicitHeight: 28
                implicitWidth: 72
                onClicked: pathsDialog.close()
                background: Rectangle {
                    radius: 6
                    color: parent.hovered ? cAccentDark : cPanel2
                    border.color: cLine
                }
                contentItem: Label {
                    text: parent.text
                    color: parent.hovered ? cOnColor : cText
                    font.pixelSize: 11
                }
            }
        }

        Connections {
            target: backend
            function onRestartRequired(msg) {
                pathsDialog.restartNote = msg + " — " + I18n.t("paths.restartHint")
                pathsDialog.reload()
            }
        }
    }

    // ---------- 单条路径编辑（含迁移确认） ----------
    Dialog {
        id: pathEditDialog
        objectName: "pathEditDialog"
        modal: true
        anchors.centerIn: parent
        width: 560
        padding: 0

        property string targetKey: ""
        property string targetDesc: ""
        property string oldPath: ""
        property string newPath: ""
        property bool migrate: true
        property string preview: ""

        function refreshPreview() {
            if (newPath.length === 0) {
                preview = I18n.t("paths.resetPreview")
                return
            }
            var r = backend.previewPathMove(targetKey, newPath)
            preview = r.msg
        }
        onNewPathChanged: if (visible) refreshPreview()
        onOpened: { migrate = true; refreshPreview() }

        background: Rectangle {
            radius: 12
            color: cPanel
            border.color: cLine
            border.width: 1
        }

        header: Label {
            text: I18n.t("paths.editTitle", pathEditDialog.targetDesc)
            color: cText
            font.pixelSize: 14
            font.bold: true
            leftPadding: 18
            topPadding: 14
            elide: Text.ElideRight
        }

        contentItem: ColumnLayout {
            spacing: 8
            anchors.margins: 18

            Label {
                Layout.fillWidth: true
                text: I18n.t("paths.current") + "：" + pathEditDialog.oldPath
                color: cTextDim
                font.pixelSize: 10
                elide: Text.ElideMiddle
            }

            RowLayout {
                spacing: 6
                TextField {
                    id: newPathField
                    Layout.fillWidth: true
                    text: pathEditDialog.newPath
                    placeholderText: I18n.t("paths.newPlaceholder")
                    color: cText
                    placeholderTextColor: cTextDim
                    selectByMouse: true
                    onTextChanged: pathEditDialog.newPath = text
                    background: Rectangle {
                        radius: 6
                        color: cBg
                        border.color: newPathField.activeFocus ? cAccent : cLine
                        border.width: newPathField.activeFocus ? 2 : 1
                    }
                }
                Button {
                    text: I18n.t("paths.browse")
                    implicitHeight: 30
                    onClicked: pickDirDialog.open()
                    background: Rectangle {
                        radius: 6
                        color: parent.hovered ? cAccentDark : cPanel2
                        border.color: cLine
                    }
                    contentItem: Label {
                        text: parent.text
                        color: parent.hovered ? cOnColor : cText
                        font.pixelSize: 11
                    }
                }
            }

            CheckBox {
                id: migrateBox
                text: I18n.t("paths.doMigrate")
                checked: pathEditDialog.migrate
                onToggled: pathEditDialog.migrate = checked
                contentItem: Label {
                    text: migrateBox.text
                    color: cText
                    font.pixelSize: 11
                    leftPadding: migrateBox.indicator.width + 6
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Label {
                Layout.fillWidth: true
                text: pathEditDialog.migrate ? ("↪ " + pathEditDialog.preview)
                                             : I18n.t("paths.noMigrateHint")
                color: cTextDim
                font.pixelSize: 10
                wrapMode: Text.WordWrap
            }

            Label {
                Layout.fillWidth: true
                text: "⚠ " + I18n.t("paths.restartHint")
                color: cOrange
                font.pixelSize: 10
                wrapMode: Text.WordWrap
            }
        }

        footer: RowLayout {
            spacing: 8
            anchors.margins: 18
            Item { Layout.fillWidth: true }
            Button {
                text: I18n.t("btn.cancel")
                implicitHeight: 28
                implicitWidth: 72
                onClicked: pathEditDialog.close()
                background: Rectangle {
                    radius: 6
                    color: parent.hovered ? cRed : cPanel2
                    border.color: cLine
                }
                contentItem: Label {
                    text: parent.text
                    color: parent.hovered ? cOnColor : cTextDim
                    font.pixelSize: 11
                }
            }
            Button {
                text: I18n.t("btn.apply")
                implicitHeight: 28
                implicitWidth: 72
                onClicked: {
                    var r = backend.setPath(pathEditDialog.targetKey,
                                            newPathField.text, migrateBox.checked)
                    showStatus(r.msg)
                    if (r.ok) {
                        pathsDialog.reload()
                        pathEditDialog.close()
                    }
                }
                background: Rectangle {
                    radius: 6
                    color: parent.hovered ? cAccent : Theme.applyBg
                    border.color: cAccent
                }
                contentItem: Label {
                    text: parent.text
                    color: parent.hovered ? cOnColor : cText
                    font.pixelSize: 11
                }
            }
        }
    }

    // 目录选择器（folder: true 才是选目录）
    FolderDialog {
        id: pickDirDialog
        title: I18n.t("paths.browse")
        onAccepted: {
            pathEditDialog.newPath = urlToPath(pickDirDialog.selectedFolder)
            newPathField.text = pathEditDialog.newPath
        }
    }

    // ---------- 快捷键一览 ----------
    Dialog {
        id: shortcutsDialog
        objectName: "shortcutsDialog"
        modal: true
        anchors.centerIn: parent
        width: 520
        height: Math.min(560, root.height - 120)
        padding: 0

        background: Rectangle {
            radius: 12
            color: cPanel
            border.color: cLine
            border.width: 1
        }

        header: Label {
            text: I18n.t("sc.title")
            color: cText
            font.pixelSize: 15
            font.bold: true
            leftPadding: 18
            topPadding: 14
        }

        contentItem: ScrollView {
            clip: true
            anchors.margins: 18

            ColumnLayout {
                width: shortcutsDialog.width - 60
                spacing: 5

                Repeater {
                    model: [
                        { k: "Space",        d: I18n.t("sc.playPause") },
                        { k: "Ctrl+P",       d: I18n.t("sc.playPause") },
                        { k: "Ctrl+Left/Right", d: I18n.t("sc.seek") },
                        { k: "Ctrl+F",       d: I18n.t("sc.focusSearch") },
                        { k: "Ctrl+Shift+F", d: I18n.t("sc.focusScan") },
                        { k: "Esc",          d: I18n.t("sc.stopAndFocus") },
                        { k: "Ctrl+1/2/3",   d: I18n.t("sc.sideTabs") },
                        { k: "↑ / ↓",        d: I18n.t("sc.moveRow") },
                        { k: "Enter",        d: I18n.t("sc.playRow") },
                        { k: "F",            d: I18n.t("sc.favRow") },
                        { k: "S",            d: I18n.t("sc.similarRow") },
                        { k: "Enter（改标弹窗）", d: I18n.t("sc.applyCat") },
                        { k: "双击分隔条",     d: I18n.t("sc.resetSidebar") }
                    ]
                    delegate: RowLayout {
                        required property var modelData
                        width: shortcutsDialog.width - 60
                        spacing: 12
                        Label {
                            text: modelData.k
                            color: cAccent
                            font.pixelSize: 12
                            font.family: "Consolas"
                            Layout.preferredWidth: 170
                        }
                        Label {
                            text: modelData.d
                            color: cText
                            font.pixelSize: 12
                            Layout.fillWidth: true
                        }
                    }
                }
            }
        }

        footer: RowLayout {
            spacing: 8
            anchors.margins: 18
            Item { Layout.fillWidth: true }
            Button {
                text: I18n.t("sc.close")
                implicitHeight: 28
                implicitWidth: 72
                onClicked: shortcutsDialog.close()
                background: Rectangle {
                    radius: 6
                    color: parent.hovered ? cAccentDark : cPanel2
                    border.color: cLine
                }
                contentItem: Label {
                    text: parent.text
                    color: parent.hovered ? cOnColor : cText
                    font.pixelSize: 11
                }
            }
        }
    }

    // ---------- 关于 ----------
    Dialog {
        id: aboutDialog
        objectName: "aboutDialog"
        modal: true
        anchors.centerIn: parent
        width: 460
        padding: 0

        background: Rectangle {
            radius: 12
            color: cPanel
            border.color: cLine
            border.width: 1
        }

        header: Label {
            text: I18n.t("menu.about")
            color: cText
            font.pixelSize: 15
            font.bold: true
            leftPadding: 18
            topPadding: 14
        }

        contentItem: ColumnLayout {
            spacing: 10
            anchors.margins: 18

            Label {
                Layout.fillWidth: true
                text: I18n.t("about.text")
                color: cText
                font.pixelSize: 12
                lineHeight: 1.5
                wrapMode: Text.WordWrap
            }
            Label {
                Layout.fillWidth: true
                text: I18n.t("about.version", backend.appVersion())
                color: cTextDim
                font.pixelSize: 10
            }
            Label {
                Layout.fillWidth: true
                text: I18n.t("about.dataAt") + "：" + backend.pathInfo()[0].path
                color: cTextDim
                font.pixelSize: 10
                elide: Text.ElideMiddle
            }
        }

        footer: RowLayout {
            spacing: 8
            anchors.margins: 18
            Item { Layout.fillWidth: true }
            Button {
                text: I18n.t("about.ok")
                implicitHeight: 28
                implicitWidth: 72
                onClicked: aboutDialog.close()
                background: Rectangle {
                    radius: 6
                    color: parent.hovered ? cAccent : Theme.applyBg
                    border.color: cAccent
                }
                contentItem: Label {
                    text: parent.text
                    color: parent.hovered ? cOnColor : cText
                    font.pixelSize: 11
                }
            }
        }
    }

    // ---------- 拖入参考音频 → 以声搜声（全窗口） ----------
    DropArea {
        id: dropZone
        anchors.fill: parent
        onDropped: function(drop) { root.similarFromDrop(drop) }
        onEntered: {
            if (drag.hasUrls && drag.urls.length > 0) dragHint.visible = true
        }
        onExited: dragHint.visible = false
    }

    Rectangle {
        id: dragHint
        anchors.fill: parent
        visible: false
        color: Theme.overlay
        z: 9000
        border.color: cAccent
        border.width: 3
        Text {
            anchors.centerIn: parent
            text: I18n.t("drop.hint")
            horizontalAlignment: Text.AlignHCenter
            color: cText
            font.pixelSize: 22
        }
    }

    // ---------- 收藏导入文件选择 ----------
    FileDialog {
        id: importFavDialog
        title: I18n.t("fav.importTitle")
        nameFilters: ["收藏文件（Favorites） (*.md *.csv *.m3u *.txt)", "所有文件（All files） (*.*)"]
        onAccepted: root.chooseImportFile(importFavDialog.selectedFile)
    }

    // ---------- 初始 ----------
    Component.onCompleted: {
        backend.refreshStats()
        catalogList = backend.ucsCatalogList
        searchField.forceActiveFocus()
        // 收藏 / 保存搜索为持久数据：backend 构造时已从 %APPDATA% 载入，此处同步到前端
        syncFavorites()
        savedList = backend.savedSearches
        syncSaved()
    }
}