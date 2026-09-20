import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

ApplicationWindow {
    id: root
    width: 1380
    height: 880
    minimumWidth: 1000
    minimumHeight: 640
    visible: true
    color: cBg
    title: "SoundCatcher — 本地 AI 音效库（Local AI Sound Library）"

    // ---------- 暗色主题 ----------
    readonly property color cBg: "#1c1d22"
    readonly property color cPanel: "#23252d"
    readonly property color cPanel2: "#2a2d37"
    readonly property color cLine: "#363b48"
    readonly property color cText: "#d9dce3"
    readonly property color cTextDim: "#8d93a1"
    readonly property color cAccent: "#7aa2f7"
    readonly property color cAccentDark: "#5d83d9"
    readonly property color cGreen: "#9ece6a"
    readonly property color cOrange: "#ff9e64"
    readonly property color cRed: "#f7768e"
    readonly property color cRowHover: "#30323e"
    readonly property color cRowSel: "#39415a"

    // ---------- 状态 ----------
    property int libTotal: 0
    property int libEmbedded: 0
    property int libFailed: 0
    property string statusNote: ""
    property string ucsHint: ""
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
        if (!fileId || fileId <= 0) { showStatus("该条目没有 fileId，无法改标"); return }
        if (catalogList.length === 0) { showStatus("UCS 语料未就绪（data/ucs/catalog.json）"); return }
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
            showStatus("请拖入一个音频文件（不支持文件夹/文本）")
            return
        }
        var p = urlToPath(drop.urls[0])
        var ext = p.slice(p.lastIndexOf(".") + 1).toLowerCase()
        if (["wav","aif","aiff","flac","mp3","m4a","ogg","opus","caf","rf64","wma","aac"].indexOf(ext) < 0) {
            showStatus("不支持的文件类型：" + ext + "（请拖入音频文件）")
            return
        }
        dragHint.visible = false
        backend.doSimilar(p, 60)
        showStatus("以声搜声：" + p.slice(p.lastIndexOf("/") + 1))
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
        statusNote = (backend.isFavorite(it.path) ? "★ 已收藏：" : "☆ 已取消：") + it.filename
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
        statusNote = "已展开全部 " + n + " 个 UCS 分类"
    }
    function collapseAllUcs() {
        var n = backend.ucsModelCount
        for (var r = 0; r < n; r++) ucsTreeView.collapse(ucsTreeView.index(r, 0))
        statusNote = "已折叠全部分类"
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
            statusNote = "Hit（命中）" + items.length + " · Latency（延迟）已记录"
            emptyText.text = items.length === 0 ? "No results（无结果）— 换个说法试试" : ""
        }
        function onSearchFailed(msg) {
            statusNote = "✗ " + msg
            emptyText.text = msg
        }
        function onTranslationNote(note) {
            statusNote = note
        }
        function onStatsChanged(total, embedded, failed) {
            libTotal = total; libEmbedded = embedded; libFailed = failed
        }
        function onQueryLatency(sec) {
            statusNote = "Query（查询）耗时 " + (sec * 1000).toFixed(1) + " ms"
        }
        function onWaveformReady(fileId, peaks) {
            waveCanvas.peaks = peaks
        }
        function onUcsTreeChanged() {
            ucsHint = backend.ucsModelCount === 0
                ? "未找到 UCS 语料（data/ucs/catalog.json）— 先运行 soundcatcher ucs init"
                : "点击叶子分类浏览 · 计数随 ucs tag 推进"
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
            statusNote = "UCS Browse（分类浏览）· " + items.length + " 条"
            emptyText.text = items.length === 0 ? "该分类暂无已打标文件（等待 ucs tag 全量打标）" : ""
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
                        text: "SoundCatcher"
                        color: cText
                        font.pixelSize: 18
                        font.bold: true
                    }
                    Label {
                        text: "全离线音效库（Offline Sound Library）"
                        color: cTextDim
                        font.pixelSize: 11
                    }
                }

                // 模式切换（checkable 三选一：Semantic / Keyword / Hybrid）
                // 自定义 background + contentItem 以适配暗色主题（默认样式的文字为深色，在深底上不可见）
                ButtonGroup { id: modeGroup }
                Button {
                    id: modeSemantic
                    text: "Semantic（语义）"
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
                        color: modeSemantic.checked ? "#10131a" : cText
                        font.pixelSize: 11
                        font.bold: modeSemantic.checked
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                Button {
                    id: modeKeyword
                    text: "Keyword（关键词）"
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
                        color: modeKeyword.checked ? "#10131a" : cText
                        font.pixelSize: 11
                        font.bold: modeKeyword.checked
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                Button {
                    id: modeHybrid
                    text: "Hybrid（混合）"
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
                        color: modeHybrid.checked ? "#10131a" : cText
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
                    placeholderText: "Search sounds（搜索音效）— 中文/英文均可，如：玻璃破碎，带回响的"
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
                    text: "Search（搜索）"
                    enabled: searchField.text.trim().length > 0
                    onClicked: root.doSearch()
                    background: Rectangle {
                        radius: 8
                        color: searchBtn.enabled ? cAccent : cPanel2
                        border.color: cAccent
                    }
                    contentItem: Label {
                        text: searchBtn.text
                        color: searchBtn.enabled ? "#10131a" : cTextDim
                        font.bold: true
                    }
                }
            }
        }

        // ================= 主体 =================
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // ---------- 左侧栏 ----------
            Rectangle {
                Layout.preferredWidth: 320
                Layout.minimumWidth: 300
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
                                text: "Library（音效库）"
                                color: cTextDim
                                font.pixelSize: 11
                            }
                            Label {
                                text: root.libTotal + " files（文件）"
                                color: cText
                                font.pixelSize: 16
                                font.bold: true
                            }
                            // 侧栏窄（236~264px），横向并排两行一定被截断
                            // → 改成上/下两行，各自独占整行宽度
                            Label {
                                text: "Embedded（已嵌入）: " + root.libEmbedded
                                color: cGreen
                                font.pixelSize: 11
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            Label {
                                text: "Failed（失败）: " + root.libFailed
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
                                text: "Scan（扫描目录）"
                                color: cTextDim
                                font.pixelSize: 11
                            }
                            RowLayout {
                                spacing: 6
                                TextField {
                                    id: scanDirField
                                    Layout.fillWidth: true
                                    placeholderText: "目录，如 D:\\音效库"
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
                                    text: backend.scanState === "running" ? "Stop（停止）" : "Start（开始）"
                                    implicitWidth: 92
                                    onClicked: {
                                        showStatus(backend.scanState === "running"
                                                   ? backend.stopScan()
                                                   : backend.startScan(scanDirField.text))
                                    }
                                    background: Rectangle {
                                        radius: 7
                                        color: backend.scanState === "running"
                                              ? (parent.hovered ? cRed : "#5a3a44")
                                              : (parent.hovered ? cAccentDark : cPanel)
                                        border.color: backend.scanState === "running" ? cRed : cLine
                                    }
                                    contentItem: Label {
                                        text: parent.text
                                        color: parent.hovered ? "#10131a" : cText
                                        font.pixelSize: 11
                                    }
                                }
                            }
                            Label {
                                text: backend.scanState === "running"
                                      ? "◉ " + backend.scanMessage
                                      : (backend.scanMessage.length > 0
                                         ? backend.scanMessage
                                         : "子进程独立写库，GUI 只读共存（WAL）")
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
                        readonly property real _avail: width - spacing * 2
                        TabButton {
                            id: tabUcs
                            text: "UCS 分类"
                            width: sideTabs._avail * sideTabs._wUcs / sideTabs._wSum
                            background: Rectangle {
                                radius: 6
                                color: tabUcs.checked ? cAccent : (tabUcs.hovered ? cPanel2 : cPanel)
                                border.color: tabUcs.checked ? cAccent : cLine
                                border.width: 1
                            }
                            contentItem: Label {
                                text: tabUcs.text
                                color: tabUcs.checked ? "#10131a" : cText
                                font.pixelSize: 11
                                font.bold: tabUcs.checked
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideNone
                            }
                        }
                        TabButton {
                            id: tabHistory
                            text: "History 历史"
                            width: sideTabs._avail * sideTabs._wHis / sideTabs._wSum
                            background: Rectangle {
                                radius: 6
                                color: tabHistory.checked ? cAccent : (tabHistory.hovered ? cPanel2 : cPanel)
                                border.color: tabHistory.checked ? cAccent : cLine
                                border.width: 1
                            }
                            contentItem: Label {
                                text: tabHistory.text
                                color: tabHistory.checked ? "#10131a" : cText
                                font.pixelSize: 11
                                font.bold: tabHistory.checked
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideNone
                            }
                        }
                        TabButton {
                            id: tabFavorites
                            text: "Favorites 收藏"
                            width: sideTabs._avail * sideTabs._wFav / sideTabs._wSum
                            background: Rectangle {
                                radius: 6
                                color: tabFavorites.checked ? cAccent : (tabFavorites.hovered ? cPanel2 : cPanel)
                                border.color: tabFavorites.checked ? cAccent : cLine
                                border.width: 1
                            }
                            contentItem: Label {
                                text: tabFavorites.text
                                color: tabFavorites.checked ? "#10131a" : cText
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
                                        text: "UCS 分类树"
                                        color: cTextDim
                                        font.pixelSize: 11
                                        font.bold: true
                                    }
                                    Item { Layout.fillWidth: true }
                                    Button {
                                        text: "展开"
                                        implicitHeight: 22
                                        implicitWidth: 40
                                        onClicked: root.expandAllUcs()
                                        ToolTip.visible: hovered
                                        ToolTip.text: "展开全部 UCS 分类（Expand all）"
                                        background: Rectangle {
                                            radius: 6
                                            color: parent.hovered ? cAccentDark : cPanel2
                                            border.color: cLine
                                        }
                                        contentItem: Label {
                                            text: parent.text
                                            color: parent.hovered ? "#10131a" : cTextDim
                                            font.pixelSize: 10
                                            horizontalAlignment: Text.AlignHCenter
                                            verticalAlignment: Text.AlignVCenter
                                        }
                                    }
                                    Button {
                                        text: "折叠"
                                        implicitHeight: 22
                                        implicitWidth: 40
                                        onClicked: root.collapseAllUcs()
                                        ToolTip.visible: hovered
                                        ToolTip.text: "折叠全部分类（Collapse all）"
                                        background: Rectangle {
                                            radius: 6
                                            color: parent.hovered ? cAccentDark : cPanel2
                                            border.color: cLine
                                        }
                                        contentItem: Label {
                                            text: parent.text
                                            color: parent.hovered ? "#10131a" : cTextDim
                                            font.pixelSize: 10
                                            horizontalAlignment: Text.AlignHCenter
                                            verticalAlignment: Text.AlignVCenter
                                        }
                                    }
                                    Button {
                                        text: "刷新"
                                        implicitHeight: 22
                                        implicitWidth: 40
                                        onClicked: backend.refreshUcsTree()
                                        ToolTip.visible: hovered
                                        ToolTip.text: "重新加载分类与计数（Refresh）"
                                        background: Rectangle {
                                            radius: 6
                                            color: parent.hovered ? cAccentDark : cPanel2
                                            border.color: cLine
                                        }
                                        contentItem: Label {
                                            text: parent.text
                                            color: parent.hovered ? "#10131a" : cTextDim
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
                                        text: "Search History（历史）"
                                        color: cTextDim
                                        font.pixelSize: 11
                                        font.bold: true
                                    }
                                    Item { Layout.fillWidth: true }
                                    Button {
                                        text: "Save（保存）"
                                        implicitHeight: 24
                                        enabled: searchField.text.trim().length > 0
                                        onClicked: {
                                            backend.saveSearch(searchField.text.trim(), currentMode())
                                            showStatus("已保存搜索：" + searchField.text.trim())
                                        }
                                        background: Rectangle {
                                            radius: 6
                                            color: parent.hovered ? cAccentDark : cPanel2
                                            border.color: cLine
                                        }
                                        contentItem: Label {
                                            text: parent.text
                                            color: parent.hovered ? "#10131a" : cTextDim
                                            font.pixelSize: 11
                                        }
                                    }
                                    Button {
                                        text: "Clear（清空）"
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
                                            color: parent.hovered ? "#10131a" : cTextDim
                                            font.pixelSize: 11
                                        }
                                    }
                                }

                                // 已保存搜索（持久，%APPDATA%）
                                RowLayout {
                                    spacing: 6
                                    visible: savedModel.count > 0
                                    Label {
                                        text: "Saved（已保存，持久）"
                                        color: cGreen
                                        font.pixelSize: 10
                                        font.bold: true
                                    }
                                    Item { Layout.fillWidth: true }
                                    Label {
                                        text: savedModel.count + " 条"
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
                                                    color: parent.hovered ? "#10131a" : cTextDim
                                                    font.pixelSize: 10
                                                }
                                            }
                                        }
                                    }
                                }

                                Label {
                                    text: "Recent（本会话 " + historyModel.count + " 条）"
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
                                        text: "Favorites（收藏）"
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
                                        text: "Import（导入）"
                                        implicitHeight: 24
                                        onClicked: importFavDialog.open()
                                        ToolTip.visible: hovered
                                        ToolTip.text: "从导出的 md / csv / m3u 或路径列表文件导入收藏"
                                        background: Rectangle {
                                            radius: 6
                                            color: parent.hovered ? cAccentDark : cPanel2
                                            border.color: cLine
                                        }
                                        contentItem: Label {
                                            text: parent.text
                                            color: parent.hovered ? "#10131a" : cTextDim
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
                                        palette.highlightedText: "#10131a"
                                        background: Rectangle {
                                            radius: 6
                                            color: parent.hovered ? cAccentDark : cPanel2
                                            border.color: cLine
                                        }
                                        indicator: Label {
                                            x: exportFmtBox.width - 18
                                            y: exportFmtBox.height / 2 - 6
                                            text: "▾"
                                            color: exportFmtBox.hovered ? "#10131a" : cTextDim
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
                                                color: parent.highlighted ? "#10131a" : cText
                                                font.pixelSize: 10
                                                leftPadding: 8
                                                verticalAlignment: Text.AlignVCenter
                                            }
                                        }
                                    }
                                    Button {
                                        text: "Export（导出）"
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
                                            color: parent.hovered ? "#10131a" : cTextDim
                                            font.pixelSize: 11
                                        }
                                    }
                                }
                                Label {
                                    visible: favoritesModel.count === 0
                                    text: "在结果行点 ☆ 收藏 · 持久化到 %APPDATA%\\SoundCatcher"
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
                                                    color: parent.hovered ? "#10131a" : cTextDim
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
                    Label {
                        Layout.fillWidth: true
                        text: {
                            if (backend.searching) return "Searching…（搜索中）"
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
                Layout.fillWidth: true
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
                            text: "Results（结果）"
                            color: cTextDim
                            font.pixelSize: 12
                            font.bold: true
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
                            text: "输入查询开始搜索（Type a query to start）"
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
                                        color: resultView.currentIndex === index ? "#10131a" : cTextDim
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
                                    ToolTip.text: fav ? "取消收藏（Unfavorite）" : "收藏（Add to favorites）"
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
                                    text: "Similar（相似）"
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
                                        color: parent.hovered ? "#10131a" : cText
                                        font.pixelSize: 12
                                    }
                                }

                                Button {
                                    text: "改标（Relabel）"
                                    onClicked: {
                                        root.openRelabel(row.model.fileId, row.model.filename)
                                        resultView.currentIndex = index
                                    }
                                    ToolTip.visible: hovered
                                    ToolTip.text: "人工修正 UCS 分类（写回 ucs_labels）"
                                    background: Rectangle {
                                        radius: 7
                                        color: parent.hovered ? "#4a6b5a" : cPanel2
                                        border.color: parent.hovered ? cGreen : cLine
                                    }
                                    contentItem: Label {
                                        text: parent.text
                                        color: parent.hovered ? "#10131a" : cText
                                        font.pixelSize: 12
                                    }
                                }
                            }
                        }
                    }
                }
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
                    text: "（未选择）（Nothing selected）"
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
                        ctx.fillStyle = "#191a20"
                        ctx.fillRect(0, 0, waveCanvas.width, waveCanvas.height)
                        if (pts.length === 0) {
                            ctx.fillStyle = "#8d93a1"
                            // Canvas 的 ctx.font 不受 QApplication 默认字体影响，
                            // 必须显式点名含 CJK 字形的族，否则中文靠系统 fallback（可能变方框）
                            ctx.font = "13px 'Microsoft YaHei UI','Microsoft YaHei','SimHei',sans-serif"
                            ctx.textAlign = "center"
                            ctx.fillText("选择结果以预览波形（Select a result to preview waveform）",
                                         waveCanvas.width / 2, waveCanvas.height / 2)
                            return
                        }
                        var mid = waveCanvas.height / 2
                        var step = waveCanvas.width / pts.length
                        ctx.strokeStyle = "#7aa2f7"
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
                        ctx.fillStyle = "#ff9e64"
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
                        contentItem: Label { text: parent.text; color: parent.hovered ? "#10131a" : cText }
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
                    Label { text: "Vol（音量）"; color: cTextDim; font.pixelSize: 11 }
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
                text: "改标（Relabel）— " + relabelPopup.targetName
                color: cText
                font.pixelSize: 14
                font.bold: true
                elide: Text.ElideMiddle
            }
            Label {
                text: "选择 UCS 子分类写回 ucs_labels（source=manual，替换该文件全部自动分类）"
                color: cTextDim
                font.pixelSize: 10
                wrapMode: Text.WordWrap
            }

            RowLayout {
                spacing: 6
                TextField {
                    id: catSearchField
                    Layout.fillWidth: true
                    placeholderText: "搜索 753 个 UCS 分类（Search），中文/英文/CatID 均可…"
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
                    text: "Clear（清除）"
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
                        color: parent.hovered ? "#10131a" : cTextDim
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
                    text: "取消（Cancel）"
                    implicitHeight: 28
                    onClicked: relabelPopup.close()
                    background: Rectangle {
                        radius: 6
                        color: parent.hovered ? cRed : cPanel2
                        border.color: cLine
                    }
                    contentItem: Label {
                        text: parent.text
                        color: parent.hovered ? "#10131a" : cTextDim
                        font.pixelSize: 11
                    }
                }
                Button {
                    text: "确定（Apply）"
                    implicitHeight: 28
                    enabled: catList.currentIndex >= 0
                    onClicked: root.doRelabel(catModel.get(catList.currentIndex).catid)
                    background: Rectangle {
                        radius: 6
                        color: parent.enabled ? (parent.hovered ? cAccent : "#3a4a6b") : cPanel2
                        border.color: parent.enabled ? cAccent : cLine
                    }
                    contentItem: Label {
                        text: parent.text
                        color: parent.enabled ? (parent.hovered ? "#10131a" : cText) : cTextDim
                        font.pixelSize: 11
                    }
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
        color: "#8010131a"
        z: 9000
        border.color: cAccent
        border.width: 3
        Text {
            anchors.centerIn: parent
            text: "松开以「以声搜声」\nDrop to search by sound"
            horizontalAlignment: Text.AlignHCenter
            color: cText
            font.pixelSize: 22
        }
    }

    // ---------- 收藏导入文件选择 ----------
    FileDialog {
        id: importFavDialog
        title: "导入收藏（Import favorites）"
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