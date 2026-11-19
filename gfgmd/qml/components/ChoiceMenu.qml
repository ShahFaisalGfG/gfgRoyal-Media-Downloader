// qmllint disable unqualified
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A small pop-up list of choices with a check on the current one (speeds, audio tracks, subtitles).
// Open it from a button with openBelow(button) or openAbove(button); `chosen(index)` reports a pick.
Popup {
    id: menu

    property string title: ""
    property var choices: []
    property int current: -1

    signal chosen(int index)

    function openAbove(anchorItem) {
        var point = anchorItem.mapToItem(menu.parent, 0, 0)
        menu.x = Math.max(0, Math.min(point.x, menu.parent.width - menu.width))
        menu.y = Math.max(0, point.y - menu.implicitHeight - 4)
        menu.open()
    }

    function openBelow(anchorItem) {
        var point = anchorItem.mapToItem(menu.parent, 0, anchorItem.height)
        menu.x = Math.max(0, Math.min(point.x, menu.parent.width - menu.width))
        menu.y = point.y + 4
        menu.open()
    }

    width: 240
    padding: Theme.spaceXs
    modal: false
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    background: Rectangle {
        radius: Theme.radiusLarge
        color: Theme.surface
        border.width: 1
        border.color: Theme.borderStrong
    }

    contentItem: ColumnLayout {
        spacing: 0

        Text {
            Layout.fillWidth: true
            Layout.margins: Theme.spaceSm
            visible: menu.title.length > 0
            text: menu.title
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            font.weight: Font.DemiBold
            color: Theme.textMuted
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(menu.choices.length * 36, 320)
            clip: true
            model: menu.choices
            currentIndex: menu.current
            keyNavigationEnabled: true
            focus: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: ItemDelegate {
                id: choice
                required property var modelData
                required property int index
                width: list.width
                height: 36
                highlighted: ListView.isCurrentItem
                Accessible.role: Accessible.RadioButton
                Accessible.name: String(choice.modelData)
                Accessible.checked: choice.index === menu.current
                onClicked: {
                    menu.chosen(choice.index)
                    menu.close()
                }
                contentItem: RowLayout {
                    spacing: Theme.spaceSm
                    Icon {
                        Layout.preferredWidth: Theme.iconLg
                        name: "check"
                        size: Theme.iconMd
                        color: Theme.accent
                        opacity: choice.index === menu.current ? 1 : 0
                    }
                    Text {
                        Layout.fillWidth: true
                        text: String(choice.modelData)
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontBody
                        color: Theme.text
                        elide: Text.ElideRight
                    }
                }
            }
            Keys.onReturnPressed: if (list.currentIndex >= 0) { menu.chosen(list.currentIndex); menu.close() }
        }
    }
}
