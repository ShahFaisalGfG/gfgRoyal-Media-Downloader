// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import "MediaKind.js" as MediaKind

// One video (or song) of a playlist, under its download in the queue: its number, thumbnail, title,
// and how it is doing, in words with an icon as well as color. The one downloading shows its
// progress; a saved one can be played.
Rectangle {
    id: entry

    signal menuRequested(int jobId, string itemId)
    // Play this saved video, with the rest of its playlist queued after it.
    signal playRequested(int jobId, string path)

    required property int index
    required property int jobId
    required property string itemId
    required property int number
    required property string title
    required property string url
    required property string kind
    required property string thumbnail
    required property string entryState
    required property string statusText
    required property real progress
    required property string detail
    required property string lastFile
    required property string format
    property bool current: false

    readonly property bool _active: entry.entryState === "active"
    readonly property color _tone: {
        switch (entry.entryState) {
        case "done":     return Theme.success
        case "archived": return Theme.success
        case "failed":   return Theme.danger
        case "skipped":
        case "deferred": return Theme.warning
        case "active":   return Theme.accent
        default:         return Theme.textMuted
        }
    }
    readonly property string _icon: {
        switch (entry.entryState) {
        case "done":     return "completed"
        case "archived": return "history"
        case "failed":   return "error"
        case "skipped":  return "skip"
        case "deferred": return "clock"
        case "active":   return "download"
        default:         return "clock"
        }
    }

    implicitHeight: 50
    radius: Theme.radius
    color: hover.hovered || entry.current ? Theme.surfaceHover : "transparent"
    border.width: entry.current && entry.ListView.view && entry.ListView.view.activeFocus ? 2 : 0
    border.color: Theme.focusRing

    Accessible.role: Accessible.ListItem
    Accessible.name: MediaKind.noun(entry.kind).charAt(0).toUpperCase() + MediaKind.noun(entry.kind).slice(1) + " "
        + entry.number + ", " + entry.title + ", "
        + entry.statusText + (entry.detail ? ", " + entry.detail : "")

    HoverHandler { id: hover }

    RowLayout {
        anchors.fill: parent
        // Indented under its download's thumbnail, so the rows read as that download's.
        anchors.leftMargin: Theme.spaceSm + 40
        anchors.rightMargin: Theme.spaceSm
        spacing: Theme.spaceSm

        Text {
            textFormat: Text.PlainText
            Layout.preferredWidth: 28
            text: entry.number
            horizontalAlignment: Text.AlignRight
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            color: Theme.textMuted
            Accessible.ignored: true
        }
        Thumb {
            Layout.preferredWidth: 64
            Layout.preferredHeight: 36
            source: entry.thumbnail
            kind: entry.kind
            label: entry.format
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2

            Text {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                text: entry.title
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                color: entry.entryState === "pending" || entry.entryState === "skipped" ? Theme.textMuted : Theme.text
                elide: Text.ElideRight
                ToolTip.visible: titleHover.hovered && truncated
                ToolTip.text: entry.title
                ToolTip.delay: 700
                HoverHandler { id: titleHover }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spaceXs

                Icon {
                    name: entry._icon
                    size: Theme.iconXs
                    color: entry._tone
                }
                Text {
                    textFormat: Text.PlainText
                    text: entry.statusText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontCaption
                    font.weight: entry._active ? Font.DemiBold : Font.Normal
                    color: entry._tone
                }
                Text {
                    textFormat: Text.PlainText
                    Layout.fillWidth: true
                    visible: entry.detail.length > 0
                    text: "·  " + entry.detail
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontCaption
                    color: Theme.textMuted
                    elide: Text.ElideRight
                }
                Item { Layout.fillWidth: true; visible: entry.detail.length === 0 }
            }
            ProgressBar {
                Layout.fillWidth: true
                Layout.preferredHeight: 3
                visible: entry._active
                from: 0
                to: 1
                value: Math.max(0, entry.progress)
                indeterminate: entry.progress < 0
                Accessible.name: "Progress of " + entry.title
            }
        }

        AppButton {
            visible: entry.lastFile.length > 0
            kind: "ghost"
            compact: true
            iconName: "play"
            toolTipText: entry.kind === "photo" ? "View this picture" : "Play this " + MediaKind.noun(entry.kind)
            onClicked: entry.playRequested(entry.jobId, entry.lastFile)
        }
        AppButton {
            kind: "ghost"
            compact: true
            iconName: "more"
            toolTipText: "More actions"
            onClicked: entry.menuRequested(entry.jobId, entry.itemId)
        }
    }

    MouseArea {
        anchors.fill: parent
        z: -1
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: function (mouse) {
            if (entry.ListView.view) entry.ListView.view.currentIndex = entry.index
            if (mouse.button === Qt.RightButton) entry.menuRequested(entry.jobId, entry.itemId)
        }
        onDoubleClicked: if (entry.lastFile.length > 0) entry.playRequested(entry.jobId, entry.lastFile)
    }
}
