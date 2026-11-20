// qmllint disable unqualified
import QtQuick
import QtQuick.Layouts

// One file in the Library: cover, title, details, and Play, Show in folder, and More. Inside an open
// playlist or channel group it is indented under the group and numbered by its place in the list.
Rectangle {
    id: record

    signal playRequested(string path, string groupKey)
    signal menuRequested(int historyId, string url, bool missing, string kind, string title)
    signal selectToggled(int historyId, int index)
    signal rangeRequested(int index)

    required property int index
    required property int historyId
    required property string groupKey
    required property string title
    required property string uploader
    required property string site
    required property string kind
    required property string path
    required property string fileName
    required property string sizeText
    required property string dateText
    required property string durationText
    required property string qualityText
    required property string url
    required property bool missing
    required property string thumbnail
    required property string format
    required property int number
    required property bool inGroup
    property bool current: false
    property bool selected: false
    // Some file is picked, so every row shows its mark.
    property bool selecting: false
    // The keyboard's current row in a list that has focus.
    readonly property bool _focused: record.current && !!record.ListView.view && record.ListView.view.activeFocus

    implicitHeight: record.inGroup ? 58 : 68
    radius: Theme.radius
    color: record.selected ? Theme.accentSoft
        : rowHover.hovered || record.current ? Theme.surfaceHover : "transparent"
    border.width: record._focused ? 2 : 0
    border.color: Theme.focusRing
    Accessible.role: Accessible.ListItem
    Accessible.name: (record.inGroup ? record.number + ", " : "") + record.title
        + (record.kind === "audio" ? ", song" : ", video") + (record.missing ? ", file moved or deleted" : "")
    Accessible.selectable: true
    Accessible.selected: record.selected
    HoverHandler { id: rowHover }

    RowLayout {
        anchors.fill: parent
        // Inside a group, the files sit under the group's cover, numbered.
        anchors.leftMargin: record.inGroup ? Theme.spaceSm + 40 : Theme.spaceSm
        anchors.rightMargin: Theme.spaceSm
        spacing: Theme.spaceMd

        Text {
            textFormat: Text.PlainText
            visible: record.inGroup
            Layout.preferredWidth: 28
            text: record.number
            horizontalAlignment: Text.AlignRight
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            color: Theme.textMuted
            Accessible.ignored: true
        }
        Thumb {
            Layout.preferredWidth: record.inGroup ? 72 : 88
            Layout.preferredHeight: record.inGroup ? 40 : 50
            source: record.thumbnail
            kind: record.kind
            label: record.format
            opacity: record.missing ? 0.5 : 1

            SelectMark {
                checked: record.selected
                shown: record.selecting || rowHover.hovered || record._focused
                itemName: record.title
                onToggled: record.selectToggled(record.historyId, record.index)
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 3
            Text {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                text: record.title
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                font.weight: record.inGroup ? Font.Normal : Font.DemiBold
                color: record.missing ? Theme.textMuted : Theme.text
                elide: Text.ElideRight
            }
            Text {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                text: record.missing ? "Moved or deleted: " + record.fileName
                    : [record.inGroup ? "" : record.uploader, record.inGroup ? "" : record.site, record.qualityText,
                       record.durationText, record.sizeText, record.inGroup ? "" : record.dateText]
                      .filter(part => part.length > 0).join("  ·  ")
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: record.missing ? Theme.warning : Theme.textMuted
                elide: Text.ElideRight
            }
        }
        AppButton {
            visible: !record.missing
            kind: "ghost"
            compact: true
            iconName: "play"
            toolTipText: record.inGroup ? "Play from here (Enter)" : "Play here (Enter)"
            onClicked: record.playRequested(record.path, record.groupKey)
        }
        AppButton {
            visible: !record.missing
            kind: "ghost"
            compact: true
            iconName: "folderOpen"
            toolTipText: "Show in folder"
            onClicked: appController.revealFile(record.path)
        }
        AppButton {
            kind: "ghost"
            compact: true
            iconName: "more"
            toolTipText: "More actions"
            onClicked: record.menuRequested(record.historyId, record.url, record.missing, record.kind, record.title)
        }
    }
    MouseArea {
        anchors.fill: parent
        z: -1
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: function (mouse) {
            if (record.ListView.view) record.ListView.view.currentIndex = record.index
            if (mouse.button === Qt.RightButton)
                record.menuRequested(record.historyId, record.url, record.missing, record.kind, record.title)
            else if (mouse.modifiers & Qt.ControlModifier) record.selectToggled(record.historyId, record.index)
            else if (mouse.modifiers & Qt.ShiftModifier) record.rangeRequested(record.index)
        }
        onDoubleClicked: if (!record.missing) record.playRequested(record.path, record.groupKey)
    }
}
