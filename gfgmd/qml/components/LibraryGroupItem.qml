// qmllint disable unqualified
import QtQuick
import QtQuick.Layouts

// A playlist's or channel's files in the Library, as one row: its newest cover, its name, how many
// songs and videos, and Play all. Its button opens it into its files, listed under it in order;
// picking it picks all of them.
Rectangle {
    id: group

    signal expandToggled(string groupKey, bool expanded)
    signal playAllRequested(string groupKey)
    signal menuRequested(string groupKey, string title, string kind, string folder)
    signal selectToggled(string groupKey, int index)
    signal rangeRequested(int index)

    required property int index
    required property string groupKey
    required property string title
    required property string site
    required property string kind
    required property string path
    required property string thumbnail
    required property string dateText
    required property string countText
    required property int fileCount
    required property bool expanded
    property bool current: false
    property bool selected: false
    property bool selecting: false
    // The keyboard's current row in a list that has focus.
    readonly property bool _focused: group.current && !!group.ListView.view && group.ListView.view.activeFocus

    implicitHeight: 68
    radius: Theme.radius
    color: group.selected ? Theme.accentSoft
        : hover.hovered || group.current ? Theme.surfaceHover : "transparent"
    border.width: group._focused ? 2 : 0
    border.color: Theme.focusRing
    Accessible.role: Accessible.ListItem
    Accessible.name: group.title + ", " + group.countText + (group.expanded ? ", open" : ", closed")
    Accessible.selectable: true
    Accessible.selected: group.selected
    HoverHandler { id: hover }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.spaceSm
        anchors.rightMargin: Theme.spaceSm
        spacing: Theme.spaceMd

        Thumb {
            Layout.preferredWidth: 88
            Layout.preferredHeight: 50
            source: group.thumbnail
            kind: group.kind
            label: "" + group.fileCount

            SelectMark {
                checked: group.selected
                shown: group.selecting || hover.hovered || group._focused
                itemName: group.title
                onToggled: group.selectToggled(group.groupKey, group.index)
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 3
            Text {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                text: group.title
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                font.weight: Font.DemiBold
                color: Theme.text
                elide: Text.ElideRight
            }
            Text {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                text: [group.countText, group.site, group.dateText].filter(part => part.length > 0).join("  ·  ")
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.textMuted
                elide: Text.ElideRight
            }
        }
        AppButton {
            kind: "ghost"
            compact: true
            text: group.fileCount + (group.kind === "audio" ? (group.fileCount === 1 ? " song" : " songs")
                                                             : (group.fileCount === 1 ? " video" : " videos"))
            iconName: group.expanded ? "chevronDown" : "chevronRight"
            Accessible.name: (group.expanded ? "Hide " : "Show ") + group.title
            onClicked: group.expandToggled(group.groupKey, !group.expanded)
        }
        AppButton {
            kind: "ghost"
            compact: true
            iconName: "play"
            toolTipText: "Play all, in order (Enter)"
            onClicked: group.playAllRequested(group.groupKey)
        }
        AppButton {
            kind: "ghost"
            compact: true
            iconName: "more"
            toolTipText: "More actions"
            onClicked: group.menuRequested(group.groupKey, group.title, group.kind, group.path)
        }
    }
    MouseArea {
        anchors.fill: parent
        z: -1
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: function (mouse) {
            if (group.ListView.view) group.ListView.view.currentIndex = group.index
            if (mouse.button === Qt.RightButton) group.menuRequested(group.groupKey, group.title, group.kind, group.path)
            else if (mouse.modifiers & Qt.ControlModifier) group.selectToggled(group.groupKey, group.index)
            else if (mouse.modifiers & Qt.ShiftModifier) group.rangeRequested(group.index)
        }
        onDoubleClicked: group.expandToggled(group.groupKey, !group.expanded)
    }
}
