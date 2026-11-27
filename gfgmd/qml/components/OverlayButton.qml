// qmllint disable unqualified
import QtQuick
import QtQuick.Controls

// A button drawn over a video or picture (the player's and the photo viewer's control bars): an icon
// or short text, light on the dark bar in both themes, with a checked state and a tooltip.
AbstractButton {
    id: button

    property string iconName: ""
    property string toolTipText: ""

    implicitWidth: button.text.length > 0 ? label.implicitWidth + 20 : 36
    implicitHeight: 36
    focusPolicy: Qt.TabFocus
    hoverEnabled: true
    opacity: button.enabled ? 1 : 0.4
    Accessible.role: Accessible.Button
    Accessible.name: button.toolTipText || button.text
    Accessible.checkable: button.checkable
    Accessible.checked: button.checked
    ToolTip.visible: button.toolTipText.length > 0 && (button.hovered || button.visualFocus)
    ToolTip.text: button.toolTipText
    ToolTip.delay: 500

    background: Rectangle {
        radius: Theme.radius
        color: button.down ? Theme.overlayPressed : button.checked ? Theme.overlayChecked
            : button.hovered ? Theme.overlayHover : "transparent"
        border.width: button.visualFocus ? 2 : 0
        border.color: Theme.overlayText
        Behavior on color { ColorAnimation { duration: Theme.motionFast } }
    }
    contentItem: Item {
        Icon {
            anchors.centerIn: parent
            visible: button.text.length === 0
            name: button.iconName
            size: Theme.iconLg
            color: button.checked ? Theme.overlayAccent : Theme.overlayText
        }
        Text {
            id: label
            textFormat: Text.PlainText
            anchors.centerIn: parent
            visible: button.text.length > 0
            text: button.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            font.weight: Font.DemiBold
            color: Theme.overlayText
        }
    }
}
