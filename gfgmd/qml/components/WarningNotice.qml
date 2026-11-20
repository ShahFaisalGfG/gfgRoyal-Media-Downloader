import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A warning line for the main window's bottom bar: an icon, a one-line message that shows in full
// on hover when cut short, and any children (action buttons, app icons) at the end of the line.
// It matches UpdateNotice's look; UpdateNotice does not build on it because that file is kept
// identical in gfgLock and CC-Gen-Ultimate.
Rectangle {
    id: notice

    property string iconName: "warning"
    property string text: ""
    // The items at the end of the line. They keep their width; the message is cut short instead.
    default property alias trailing: trailingRow.data

    implicitHeight: row.implicitHeight + 2 * Theme.spaceXs
    radius: Theme.radius
    color: Theme.warningSoft

    RowLayout {
        id: row
        anchors.fill: parent
        anchors.leftMargin: Theme.spaceSm
        anchors.rightMargin: Theme.spaceXs
        spacing: Theme.spaceSm

        Icon {
            Layout.minimumWidth: implicitWidth
            name: notice.iconName
            size: Theme.iconMd
            color: Theme.warning
        }
        Text {
            textFormat: Text.PlainText
            id: message
            Layout.fillWidth: true
            text: notice.text
            elide: Text.ElideRight
            maximumLineCount: 1
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            color: Theme.text
            Accessible.role: Accessible.StaticText
            Accessible.name: text
            HoverHandler { id: messageHover }
            ToolTip.visible: messageHover.hovered && message.truncated
            ToolTip.text: message.text
            ToolTip.delay: 500
        }
        RowLayout {
            id: trailingRow
            Layout.minimumWidth: implicitWidth
            spacing: Theme.spaceSm
        }
    }
}
