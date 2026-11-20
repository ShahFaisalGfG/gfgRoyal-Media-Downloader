// qmllint disable unqualified
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A playlist's or channel's videos with check boxes: filter, all, none, new only, or a number range.
ColumnLayout {
    id: list

    required property var model
    // The count of the list the range boxes were last set for.
    property int _loadedCount: -1

    spacing: Theme.spaceSm

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spaceSm

        StyledTextField {
            Layout.fillWidth: true
            placeholderText: "Filter by title"
            accessibleName: "Filter the videos by title"
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
            toolTipText: "Check only videos you haven't downloaded with these choices"
            onClicked: list.model.checkNew()
        }
    }

    RowLayout {
        spacing: Theme.spaceSm
        Text {
            textFormat: Text.PlainText
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
        Text { textFormat: Text.PlainText; text: "to"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textMuted }
        StyledSpinBox {
            id: last
            from: 1
            to: Math.max(1, list.model.totalCount)
            // Set when a list loads, not bound: checking a range changes the count's signal, which
            // would put back the whole list's last number over the one typed.
            Component.onCompleted: last.value = Math.max(1, list.model.totalCount)
            Accessible.name: "Last video number"
        }
        Connections {
            target: list.model
            // A new list (another count), not a filter typed over the same one.
            function onModelReset() {
                if (list.model.totalCount === list._loadedCount) return
                list._loadedCount = list.model.totalCount
                // Once the boxes' limits follow the new count, which changes just after the reset;
                // set now, the last number would be cut to the old list's limit.
                Qt.callLater(function () {
                    first.value = 1
                    last.value = Math.max(1, list.model.totalCount)
                })
            }
        }
        AppButton {
            kind: "ghost"
            text: "Check range"
            toolTipText: "Check the videos numbered from the first to the last value and clear the rest"
            onClicked: list.model.checkRange(first.value, last.value)
        }
        Item { Layout.fillWidth: true }
        Text {
            textFormat: Text.PlainText
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
        readonly property int rowHeight: 36
        Layout.fillWidth: true
        // From the row count, not contentHeight: a ListView only estimates contentHeight from the rows
        // it has created, which changes with its own height and would keep the layout resizing.
        Layout.preferredHeight: Math.min(count, 8) * view.rowHeight
        clip: true
        model: list.model
        reuseItems: true
        cacheBuffer: 400
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        // One Tab stop: Up and Down move between videos, Page Up and Page Down by a page, Home and End
        // to the ends, and Space checks or clears the current one.
        keyNavigationEnabled: true
        activeFocusOnTab: true
        Accessible.role: Accessible.List
        Accessible.name: "Videos to download"
        Keys.onSpacePressed: list.model.toggle(view.currentIndex)
        Keys.onPressed: function (event) {
            var page = Math.max(1, Math.floor(view.height / view.rowHeight) - 1)
            var row
            switch (event.key) {
            case Qt.Key_PageUp:   row = view.currentIndex - page; break
            case Qt.Key_PageDown: row = view.currentIndex + page; break
            case Qt.Key_Home:     row = 0; break
            case Qt.Key_End:      row = view.count - 1; break
            default: return
            }
            if (view.count > 0) view.currentIndex = Math.max(0, Math.min(view.count - 1, row))
            event.accepted = true
        }

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
            height: view.rowHeight
            color: entryHover.hovered || ListView.isCurrentItem ? Theme.surfaceHover : "transparent"
            radius: Theme.radius
            border.width: ListView.isCurrentItem && view.activeFocus ? 2 : 0
            border.color: Theme.focusRing
            // The row is the check box for screen readers; the box drawn inside it is skipped.
            Accessible.role: Accessible.CheckBox
            Accessible.name: entry.title
            Accessible.description: "Number " + entry.position + (entry.durationText ? ", " + entry.durationText : "")
                + (entry.archived ? ", downloaded" : "") + (entry.unavailable ? ", needs sign-in" : "")
            Accessible.checkable: true
            Accessible.checked: entry.checked
            Accessible.onPressAction: list.model.toggle(entry.index)
            Accessible.onToggleAction: list.model.toggle(entry.index)
            HoverHandler { id: entryHover }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.spaceXs
                anchors.rightMargin: Theme.spaceSm
                spacing: Theme.spaceSm
                CheckBox {
                    checked: entry.checked
                    onClicked: list.model.toggle(entry.index)
                    focusPolicy: Qt.NoFocus
                    Accessible.ignored: true
                }
                Text {
                    textFormat: Text.PlainText
                    Layout.preferredWidth: 40
                    text: entry.position
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontCaption
                    color: Theme.textMuted
                    horizontalAlignment: Text.AlignRight
                }
                Text {
                    textFormat: Text.PlainText
                    Layout.fillWidth: true
                    text: entry.title
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontBody
                    color: entry.unavailable ? Theme.textMuted : Theme.text
                    elide: Text.ElideRight
                }
                StatusBadge { visible: entry.archived; text: "Downloaded"; iconName: "completed"; tone: "success" }
                StatusBadge { visible: entry.unavailable; text: "Needs sign-in"; iconName: "lock"; tone: "warning" }
                Text {
                    textFormat: Text.PlainText
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
