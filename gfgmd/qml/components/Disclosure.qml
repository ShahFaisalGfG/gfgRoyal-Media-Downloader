pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

// A part that folds away, such as the Advanced choices in Download options and Preferences: its
// header opens and closes it (Enter or Space from the keyboard), and while it is closed a one-line
// summary says what the hidden choices are. Screen readers hear whether it is open.
ColumnLayout {
    id: disclosure

    property string title: "Advanced"
    // What the hidden choices are set to ("Balanced · subtitles inside the video").
    property string summary: ""
    property bool expanded: false
    default property alias content: body.data

    spacing: Theme.spaceSm

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spaceSm

        AppButton {
            id: header
            kind: "ghost"
            compact: true
            text: disclosure.title
            // One chevron that turns down as the part opens.
            iconComponent: Component {
                Icon {
                    name: "chevronRight"
                    size: Theme.iconSm
                    color: header.enabled ? Theme.text : Theme.textMuted
                    rotation: disclosure.expanded ? 90 : 0
                    Behavior on rotation { NumberAnimation { duration: Theme.motionFast; easing.type: Easing.OutQuad } }
                }
            }
            // Screen readers hear the summary with the header while the part is closed.
            Accessible.description: disclosure.expanded ? "" : disclosure.summary
            // As the Library's playlist rows: the name says whether the part is open.
            Accessible.name: disclosure.title + (disclosure.expanded ? ", open" : ", closed")
            onClicked: disclosure.expanded = !disclosure.expanded
        }
        Text {
            textFormat: Text.PlainText
            Layout.fillWidth: true
            visible: !disclosure.expanded && disclosure.summary.length > 0
            text: disclosure.summary
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            color: Theme.textMuted
            elide: Text.ElideRight
            // The header's tooltip names the part; the summary is read with it.
            Accessible.ignored: true
        }
    }

    ColumnLayout {
        id: body
        Layout.fillWidth: true
        visible: disclosure.expanded
        opacity: disclosure.expanded ? 1 : 0
        spacing: Theme.spaceSm
        Behavior on opacity { NumberAnimation { duration: Theme.motionMedium } }
    }
}
