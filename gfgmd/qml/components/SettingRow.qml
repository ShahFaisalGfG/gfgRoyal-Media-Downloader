import QtQuick
import QtQuick.Layouts

// A settings row: a label and its control on one line, with an optional hint spanning the full
// width below. Unlike FormRow, the hint is never squeezed into the label's column, so a long hint
// wraps across the whole row instead of leaving empty space beside a small control. Set
// `fillControl` for a wide control (a combo box); leave it off for a small one (a switch), so the
// label takes the width instead.
ColumnLayout {
    id: root

    property string label: ""
    property string hint: ""
    property bool fillControl: false
    default property alias control: slot.data

    Layout.fillWidth: true
    spacing: Theme.spaceXs

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spaceMd

        Text {
            Layout.fillWidth: !root.fillControl
            Layout.preferredWidth: root.fillControl ? -1 : 1
            text: root.label
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: root.enabled ? Theme.text : Theme.textMuted
            wrapMode: Text.WordWrap
            Accessible.ignored: true
        }

        RowLayout {
            id: slot
            Layout.fillWidth: root.fillControl
            Layout.alignment: Qt.AlignVCenter
            spacing: Theme.spaceSm
        }
    }

    Text {
        visible: root.hint.length > 0
        Layout.fillWidth: true
        text: root.hint
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontCaption
        color: Theme.textMuted
        wrapMode: Text.WordWrap
    }
}
