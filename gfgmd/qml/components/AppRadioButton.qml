import QtQuick
import QtQuick.Controls

// A radio button in Theme colors with its text beside it, drawn like AppCheckBox: a ring when the
// keyboard reaches it, and a tooltip on hover or keyboard focus.
RadioButton {
    id: control

    property string toolTipText: ""

    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontBody
    spacing: Theme.spaceSm
    padding: 2
    focusPolicy: Qt.StrongFocus
    Accessible.description: control.toolTipText

    ToolTip.visible: control.toolTipText.length > 0 && (control.hovered || control.visualFocus)
    ToolTip.text: control.toolTipText
    ToolTip.delay: 500
    ToolTip.timeout: control.hovered ? -1 : Theme.focusTipTimeout

    indicator: Rectangle {
        implicitWidth: 18
        implicitHeight: 18
        x: control.leftPadding
        y: control.topPadding + (control.availableHeight - height) / 2
        radius: width / 2
        color: !control.enabled ? Theme.surfaceAlt : control.hovered ? Theme.surfaceHover : Theme.surface
        border.width: control.checked ? 2 : 1
        border.color: !control.enabled ? Theme.border : control.checked ? Theme.accentFill : Theme.inputBorder

        Rectangle {
            anchors.centerIn: parent
            width: 8
            height: 8
            radius: width / 2
            visible: control.checked
            color: control.enabled ? Theme.accentFill : Theme.border
        }

        Rectangle {
            anchors.fill: parent
            anchors.margins: -3
            radius: width / 2
            color: "transparent"
            border.width: 2
            border.color: Theme.focusRing
            visible: control.visualFocus
        }
    }

    contentItem: Text {
        textFormat: Text.PlainText
        leftPadding: control.indicator.width + (control.text.length > 0 ? control.spacing : 0)
        text: control.text
        font: control.font
        color: control.enabled ? Theme.text : Theme.textMuted
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap
    }
}
