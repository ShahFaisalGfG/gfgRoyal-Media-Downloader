import QtQuick
import QtQuick.Controls

// A check box in Theme colors with its text beside it: a ring when the keyboard reaches it, and a
// tooltip on hover or keyboard focus, which screen readers get as its description.
CheckBox {
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
        radius: Theme.radius / 2
        // As AppSwitch: an outline keeps it visible unchecked (3:1), the accent fills it checked.
        color: !control.enabled ? (control.checked ? Theme.border : Theme.surfaceAlt)
            : control.checked ? Theme.accentFill
            : control.hovered ? Theme.surfaceHover : Theme.surface
        border.width: control.checked ? 0 : 1
        border.color: control.enabled ? Theme.inputBorder : Theme.border

        Icon {
            anchors.centerIn: parent
            visible: control.checked
            name: "checkMark"
            size: 12
            color: control.enabled ? Theme.textOnAccent : Theme.surface
        }

        Rectangle {
            anchors.fill: parent
            anchors.margins: -3
            radius: Theme.radius
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
