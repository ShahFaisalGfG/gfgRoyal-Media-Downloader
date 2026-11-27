// qmllint disable unqualified
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Search results from the link box, in the place of Download options: YouTube's videos, or YouTube
// Music's songs, each with its thumbnail, channel or artist, length, and views. Download takes one
// result as Download in the link box would (at once with Smart Mode, else to Download options); tick
// several to download them together. Up and Down move, Space ticks, Enter downloads, Esc closes.
Rectangle {
    id: results

    // The tallest the panel grows; the list scrolls.
    property real maxHeight: 520

    // Download these links (one result, or the ticked ones).
    signal downloadRequested(var links)
    signal closed()

    readonly property bool _empty: list.count === 0

    implicitHeight: Math.min(column.implicitHeight + 2 * Theme.spaceLg, results.maxHeight)
    radius: Theme.radiusLarge
    color: Theme.surface
    border.width: 1
    border.color: Theme.border

    function close() {
        searchController.close()
        results.closed()
    }

    Shortcut {
        sequence: "Escape"
        enabled: results.visible
        onActivated: results.close()
    }

    ColumnLayout {
        id: column
        anchors.fill: parent
        anchors.margins: Theme.spaceLg
        spacing: Theme.spaceMd

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm

            Icon {
                name: "search"
                size: Theme.iconMd
                color: Theme.textMuted
            }
            Text {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                text: (searchController.music ? "Songs for " : "Videos for ") + "“" + searchController.query + "”"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSubtitle
                font.weight: Font.DemiBold
                color: Theme.text
                elide: Text.ElideRight
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
            AppButton {
                visible: searchController.checkedCount > 0
                kind: "primary"
                compact: true
                iconName: "download"
                text: "Download " + searchController.checkedCount
                onClicked: results.downloadRequested(searchController.checkedLinks())
            }
            AppButton {
                visible: searchController.checkedCount > 0
                kind: "ghost"
                compact: true
                text: "Clear"
                onClicked: searchController.checkAll(false)
            }
            AppButton {
                kind: "ghost"
                compact: true
                iconName: "close"
                toolTipText: "Close the results (Esc)"
                onClicked: results.close()
            }
        }

        // Searching, nothing found, or why the search failed.
        RowLayout {
            Layout.fillWidth: true
            visible: results._empty
            spacing: Theme.spaceSm
            BusyIndicator {
                visible: searchController.busy
                running: visible
                implicitWidth: 24
                implicitHeight: 24
            }
            Text {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                text: searchController.busy ? (searchController.music ? "Searching YouTube Music..." : "Searching YouTube...")
                    : searchController.error || "Nothing found. Try other words."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                color: searchController.error && !searchController.busy ? Theme.danger : Theme.textMuted
                wrapMode: Text.WordWrap
                Accessible.role: Accessible.StaticText
                Accessible.name: text
            }
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredHeight: Math.min(contentHeight, results.maxHeight - 120)
            visible: !results._empty
            model: searchController.model
            clip: true
            spacing: 2
            boundsBehavior: Flickable.StopAtBounds
            keyNavigationEnabled: true
            activeFocusOnTab: true
            currentIndex: 0
            highlightMoveDuration: 0
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Accessible.role: Accessible.List
            Accessible.name: searchController.music ? "Songs found" : "Videos found"

            Keys.onSpacePressed: {
                var row = searchController.model.get(list.currentIndex)
                if (row.resultId) searchController.setChecked(row.resultId, !row.checked)
            }
            Keys.onReturnPressed: {
                var row = searchController.model.get(list.currentIndex)
                if (row.url) results.downloadRequested([row.url])
            }
            Keys.onEnterPressed: Keys.returnPressed(event)

            delegate: Rectangle {
                id: row
                required property int index
                required property string resultId
                required property string title
                required property string url
                required property string thumbnail
                required property string detail
                required property bool checked
                required property bool live

                width: ListView.view.width - Theme.spaceSm
                height: 66
                radius: Theme.radius
                color: rowHover.hovered || row.ListView.isCurrentItem && list.activeFocus ? Theme.surfaceHover : "transparent"
                Behavior on color { ColorAnimation { duration: Theme.motionFast } }
                Accessible.role: Accessible.ListItem
                Accessible.name: row.title + (row.detail ? ", " + row.detail : "") + (row.checked ? ", ticked" : "")
                Accessible.selected: row.checked

                HoverHandler { id: rowHover }
                TapHandler {
                    onTapped: list.currentIndex = row.index
                    onDoubleTapped: results.downloadRequested([row.url])
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spaceXs
                    anchors.rightMargin: Theme.spaceXs
                    spacing: Theme.spaceMd

                    AppCheckBox {
                        checked: row.checked
                        Accessible.name: "Tick " + row.title
                        onToggled: searchController.setChecked(row.resultId, checked)
                    }
                    Thumb {
                        Layout.preferredWidth: searchController.music ? 54 : 96
                        Layout.preferredHeight: 54
                        source: row.thumbnail
                        kind: searchController.music ? "audio" : row.live ? "live" : "video"
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            textFormat: Text.PlainText
                            Layout.fillWidth: true
                            text: row.title
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontBody
                            font.weight: Font.DemiBold
                            color: Theme.text
                            elide: Text.ElideRight
                            ToolTip.visible: titleHover.hovered && truncated
                            ToolTip.text: row.title
                            ToolTip.delay: 700
                            HoverHandler { id: titleHover }
                        }
                        Text {
                            textFormat: Text.PlainText
                            Layout.fillWidth: true
                            visible: text.length > 0
                            text: row.detail
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontCaption
                            color: Theme.textMuted
                            elide: Text.ElideRight
                        }
                    }
                    AppButton {
                        kind: "secondary"
                        compact: true
                        iconName: "download"
                        text: "Download"
                        Accessible.name: "Download " + row.title
                        onClicked: results.downloadRequested([row.url])
                    }
                }
            }

            footer: Item {
                width: list.width
                height: searchController.canMore || searchController.busy ? 44 : 0
                AppButton {
                    anchors.centerIn: parent
                    visible: searchController.canMore
                    kind: "ghost"
                    compact: true
                    text: "More results"
                    onClicked: searchController.more()
                }
                BusyIndicator {
                    anchors.centerIn: parent
                    visible: searchController.busy && !results._empty
                    running: visible
                    implicitWidth: 24
                    implicitHeight: 24
                }
            }
        }
    }
}
