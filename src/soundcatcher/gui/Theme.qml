pragma Singleton

// 主题色板：亮色 / 暗色 / 随系统 三态。
//
// 设计要点：
// - **所有颜色都必须走这里**，QML 里禁止再出现颜色字面量。原因见 09-UI修复记录.md：
//   自定义 background/contentItem 的控件若不给显式色，会继承样式默认色
//   （暗底上深色字 = 不可见）。集中管理后只需保证 Theme 自身正确。
// - `system` 态监听 Qt.styleHints.colorScheme（Qt 6.5+），系统切换主题时**热更新**。
// - `onColor` 是「强调色底上的文字色」：暗色主题下是近黑，亮色主题下是白。
//   原来硬编码的 27 处 "#10131a" 全部收敛到这一个 token。
//
// 用法（QML）：导入后直接用 `Theme.bg` / `Theme.text` …
//     import "."
//     color: Theme.bg
import QtQuick

QtObject {
    id: theme

    // ---------- 用户偏好：light | dark | system ----------
    property string mode: "dark"

    // 随系统时读这个；其余态下不被使用
    readonly property bool systemIsDark: Qt.styleHints.colorScheme === Qt.ColorScheme.Dark

    // 实际生效的是亮还是暗
    readonly property bool isDark: mode === "system" ? systemIsDark : (mode === "dark")

    // ---------- 暗色板（沿用既有配色，保持视觉不变） ----------
    readonly property var _dark: ({
        bg:          "#1c1d22",
        panel:       "#23252d",
        panel2:      "#2a2d37",
        line:        "#363b48",
        text:        "#d9dce3",
        textDim:     "#8d93a1",
        accent:      "#7aa2f7",
        accentDark:  "#5d83d9",
        green:       "#9ece6a",
        orange:      "#ff9e64",
        red:         "#f7768e",
        rowHover:    "#30323e",
        rowSel:      "#39415a",
        onColor:     "#10131a",   // 强调色底上的文字（近黑）
        canvasBg:    "#191a20",
        chipDimBg:   "#2f323c",
        chipAccentBg:"#3a4a6b",
        chipGreenBg: "#2f4538",
        dangerBg:    "#5a3a44",   // 停止按钮 hover
        applyBg:     "#3a4a6b",   // 确定按钮常态
        relabelHover:"#4a6b5a",   // 改标按钮 hover
        overlay:     "#8010131a", // 拖拽遮罩
        menuBg:      "#23252d"    // 菜单弹层背景（不黑；与 panel 同档）
    })

    // ---------- 亮色板（新增，等结构对照暗色） ----------
    readonly property var _light: ({
        bg:          "#f4f5f7",
        panel:       "#ffffff",
        panel2:      "#eceef2",
        line:        "#d3d7de",
        text:        "#1f2430",
        textDim:     "#6b7280",
        accent:      "#3b6fd4",
        accentDark:  "#2f5cb0",
        green:       "#3f8f4f",
        orange:      "#c96a1e",
        red:         "#c0392b",
        rowHover:    "#e6e9ee",
        rowSel:      "#d3ddf3",
        onColor:     "#ffffff",   // 强调色底上的文字（白）
        canvasBg:    "#e9ebef",
        chipDimBg:   "#e3e6ec",
        chipAccentBg:"#d3ddf3",
        chipGreenBg: "#d8ecdc",
        dangerBg:    "#f2d5d3",
        applyBg:     "#d3ddf3",
        relabelHover:"#d8ecdc",
        overlay:     "#80f4f5f7",
        menuBg:      "#ffffff"    // 菜单弹层背景（亮色下纯白）
    })

    readonly property var _c: isDark ? _dark : _light

    // 语义化 token（QML 侧只用这些，不碰 _c）
    readonly property color bg:           _c.bg
    readonly property color panel:        _c.panel
    readonly property color panel2:       _c.panel2
    readonly property color line:         _c.line
    readonly property color text:         _c.text
    readonly property color textDim:      _c.textDim
    readonly property color accent:       _c.accent
    readonly property color accentDark:   _c.accentDark
    readonly property color green:        _c.green
    readonly property color orange:       _c.orange
    readonly property color red:          _c.red
    readonly property color rowHover:     _c.rowHover
    readonly property color rowSel:       _c.rowSel
    readonly property color onColor:      _c.onColor
    readonly property color canvasBg:     _c.canvasBg
    readonly property color chipDimBg:    _c.chipDimBg
    readonly property color chipAccentBg: _c.chipAccentBg
    readonly property color chipGreenBg:  _c.chipGreenBg
    readonly property color dangerBg:     _c.dangerBg
    readonly property color applyBg:      _c.applyBg
    readonly property color relabelHover: _c.relabelHover
    readonly property color overlay:      _c.overlay
    readonly property color menuBg:       _c.menuBg

    // 当前色板的「暗/亮」中文标签（状态栏提示用）
    readonly property string modeLabel:
        mode === "system" ? (systemIsDark ? "随系统（当前暗色）" : "随系统（当前亮色）")
        : (isDark ? "暗色" : "亮色")

    function setMode(m) {
        if (m === "light" || m === "dark" || m === "system") mode = m
    }
}
