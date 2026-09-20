import QtQuick
import QtQuick.Controls
import "."

// 小标签：tone = dim | accent | green
// 配色全部走 Theme，禁止硬编码 —— 否则亮色主题下会保持暗色底而不可读
Rectangle {
    id: chip
    property string text: ""
    property string tone: "dim"
    property real maxWidth: 180
    property color bkg: tone === "green" ? Theme.chipGreenBg
                      : (tone === "accent" ? Theme.chipAccentBg : Theme.chipDimBg)
    property color fgc: tone === "green" ? Theme.green
                      : (tone === "accent" ? Theme.accent : Theme.textDim)
    height: 20
    radius: 4
    color: bkg
    implicitWidth: Math.min(maxWidth + 12, txt.implicitWidth + 12)
    Label {
        id: txt
        anchors.centerIn: parent
        text: chip.text
        color: chip.fgc
        font.pixelSize: 10
        elide: Text.ElideMiddle
        width: Math.min(chip.maxWidth, chip.implicitWidth - 12)
        horizontalAlignment: Text.AlignHCenter
    }
}
