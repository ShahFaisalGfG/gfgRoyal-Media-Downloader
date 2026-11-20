import QtQuick
import QtQuick.Layouts

// The bar over a list while rows are picked: how many, Select all, Clear selection (Esc), and the
// page's actions for all of them (put them inside it).
Rectangle {
    id: bar

    property int count: 0
    // Every row the list holds (with a library's filters), for "Select all".
    property int total: 0
    default property alias actions: actionRow.data

    signal selectAllRequested()
    signal clearRequested()

    implicitHeight: Theme.controlHeight + Theme.spaceSm
    radius: Theme.radius
    color: Theme.accentSoft
    Accessible.role: Accessible.ToolBar
    Accessible.name: bar.count + " selected"

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.spaceXs
        anchors.rightMargin: Theme.spaceXs
        spacing: Theme.spaceSm

        AppButton {
            kind: "ghost"
            compact: true
            iconName: "close"
            toolTipText: "Clear the selection (Esc)"
            onClicked: bar.clearRequested()
        }
        Text {
            textFormat: Text.PlainText
            text: bar.count + " selected"
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            font.weight: Font.DemiBold
            color: Theme.text
        }
        AppButton {
            visible: bar.count < bar.total
            kind: "ghost"
            compact: true
            text: "Select all " + bar.total
            toolTipText: "Select every row the list holds (Ctrl+A)"
            onClicked: bar.selectAllRequested()
        }
        Item { Layout.fillWidth: true }
        RowLayout {
            id: actionRow
            spacing: Theme.spaceXs
        }
    }
}
