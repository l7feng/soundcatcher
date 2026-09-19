import QtQuick
import QtQuick.Controls

// 小标签：tone = dim | accent | green
Rectangle {
    id: chip
    property string text: ""
    property string tone: "dim"
    property real maxWidth: 180
    property color bkg: tone === "green" ? "#2f4538" : (tone === "accent" ? "#3a4a6b" : "#2f323c")
    property color fgc: tone === "green" ? "#9ece6a" : (tone === "accent" ? "#a8c0f8" : "#8d93a1")
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