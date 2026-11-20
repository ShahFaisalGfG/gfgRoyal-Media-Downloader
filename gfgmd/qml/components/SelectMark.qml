import QtQuick
import QtQuick.Controls

// The round box on a list row's thumbnail that picks the row for actions on several at once. It
// shows while the row is hovered or is the keyboard's current row, or anything is picked, and stays
// filled while the row is picked. Put it inside the row's Thumb; it sits on the thumbnail's top-left
// corner.
Item {
    id: mark

    property bool checked: false
    // Shown even when unchecked (the row is hovered or current, or other rows are picked).
    property bool shown: false
    property string itemName: ""

    signal toggled()

    anchors.left: parent.left
    anchors.top: parent.top
    anchors.margins: 4
    width: 18
    height: 18
    visible: mark.shown || mark.checked
    Accessible.role: Accessible.CheckBox
    Accessible.name: "Select " + mark.itemName
    Accessible.checked: mark.checked
    ToolTip.visible: markHover.hovered
    ToolTip.text: mark.checked ? "Deselect (Ctrl+Space)" : "Select for actions on several at once (Ctrl+Space)"
    ToolTip.delay: 500

    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: mark.checked ? Theme.accentFill : Theme.mediaBadge
        border.width: 1.5
        border.color: Theme.mediaBadgeText
    }
    Icon {
        anchors.centerIn: parent
        visible: mark.checked
        name: "check"
        size: Theme.iconXs
        color: Theme.mediaBadgeText
    }
    // A passive handler for the tooltip, which leaves the row's own hover undisturbed.
    HoverHandler { id: markHover }
    MouseArea {
        anchors.fill: parent
        anchors.margins: -4
        cursorShape: Qt.PointingHandCursor
        onClicked: mark.toggled()
    }
}
