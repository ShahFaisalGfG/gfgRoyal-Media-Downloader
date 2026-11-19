// qmllint disable unqualified
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A playlist's or channel's videos with check boxes: filter, all, none, new only, or a number range.
ColumnLayout {
    id: list

    required property var model

    spacing: Theme.spaceSm

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spaceSm

        StyledTextField {
            Layout.fillWidth: true
            placeholderText: "Filter by title"
            toolTipText: "Show only videos whose titles contain this text; choices of hidden videos are kept"
            onTextChanged: list.model.setFilter(text)
        }
        AppButton {
            kind: "ghost"
            text: "All"
            toolTipText: "Check every video the filter shows"
            onClicked: list.model.checkVisible(true)
        }
        AppButton {
            kind: "ghost"
            text: "None"
            toolTipText: "Clear every video the filter shows"
            onClicked: list.model.checkVisible(false)
        }
        AppButton {
            kind: "ghost"
            text: "New only"
            toolTipText: "Check only videos not downloaded before in this format"
            onClicked: list.model.checkNew()
        }
    }

    RowLayout {
        spacing: Theme.spaceSm
        Text {
            text: "Numbers"
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            color: Theme.textMuted
        }
        StyledSpinBox {
            id: first
            from: 1
            to: Math.max(1, list.model.totalCount)
            value: 1
            Accessible.name: "First video number"
        }
        Text { text: "to"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textMuted }
        StyledSpinBox {
            id: last
            from: 1
            to: Math.max(1, list.model.totalCount)
            value: Math.max(1, list.model.totalCount)
            Accessible.name: "Last video number"
        }
        AppButton {
            kind: "ghost"
            text: "Check range"
            toolTipText: "Check the videos numbered from the first to the last value and clear the rest"
            onClicked: list.model.checkRange(first.value, last.value)
        }
        Item { Layout.fillWidth: true }
        Text {
            text: list.model.selectedCount + " of " + list.model.totalCount + " chosen"
                + (list.model.selectedDuration ? "  ·  " + list.model.selectedDuration : "")
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            font.weight: Font.DemiBold
            color: Theme.text
        }
    }

    ListView {
        id: view
        Layout.fillWidth: true
        // From the row count, not contentHeight: a ListView only estimates contentHeight from the rows
        // it has created, which changes with its own height and would keep the layout resizing.
        Layout.preferredHeight: Math.min(count * 36, 288)
        clip: true
        model: list.model
        reuseItems: true
        cacheBuffer: 400
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        keyNavigationEnabled: true
        Keys.onSpacePressed: list.model.toggle(view.currentIndex)

        delegate: Rectangle {
            id: entry
            required property int index
            required property string title
            required property int position
            required property string durationText
            required property bool checked
            required property bool archived
            required property bool unavailable

            width: view.width
            height: 36
            color: entryHover.hovered || ListView.isCurrentItem ? Theme.surfaceHover : "transparent"
            radius: Theme.radius
            HoverHandler { id: entryHover }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.spaceXs
                anchors.rightMargin: Theme.spaceSm
                spacing: Theme.spaceSm
                CheckBox {
                    checked: entry.checked
                    onClicked: list.model.toggle(entry.index)
                    Accessible.name: "Download " + entry.title
                    focusPolicy: Qt.NoFocus
                }
                Text {
                    Layout.preferredWidth: 40
                    text: entry.position
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontCaption
                    color: Theme.textMuted
                    horizontalAlignment: Text.AlignRight
                }
                Text {
                    Layout.fillWidth: true
                    text: entry.title
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontBody
                    color: entry.unavailable ? Theme.textMuted : Theme.text
                    elide: Text.ElideRight
                }
                StatusBadge { visible: entry.archived; text: "Downloaded"; iconName: "completed"; tone: "success" }
                StatusBadge { visible: entry.unavailable; text: "Unavailable"; iconName: "lock"; tone: "warning" }
                Text {
                    text: entry.durationText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontCaption
                    color: Theme.textMuted
                }
            }
            MouseArea {
                anchors.fill: parent
                z: -1
                onClicked: {
                    view.currentIndex = entry.index
                    list.model.toggle(entry.index)
                }
            }
        }
    }
}
