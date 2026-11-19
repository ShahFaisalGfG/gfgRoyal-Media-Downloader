// qmllint disable unqualified
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import "../components"

// Everything downloaded, newest first: search, filter by type and site, play, show in folder,
// download again, or move files to the Recycle Bin.
Item {
    id: page

    property string kindFilter: ""
    property string siteFilter: ""

    function applyFilters() {
        libraryController.setFilters(search.text, page.kindFilter, page.siteFilter)
    }
    // Play in the built-in players; the list as filtered gives them Previous and Next.
    function play(path) {
        playerController.playFrom(path, libraryController.playlist())
    }
    // Songs first (the audio bar plays them in a row), unless the list shows only videos.
    function playAll() {
        var list = libraryController.playlist()
        var wantAudio = page.kindFilter !== "video"
        var first = list.find(path => playerController.isAudio(path) === wantAudio) || list[0]
        if (first) playerController.playFrom(first, list)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spaceXl
        spacing: Theme.spaceLg

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm

            StyledTextField {
                id: search
                Layout.fillWidth: true
                placeholderText: "Search titles, channels, and file names"
                toolTipText: "Show downloads whose title, uploader, or file name contains this text"
                onTextChanged: filterTimer.restart()
            }
            StyledComboBox {
                Layout.preferredWidth: 150
                model: [{"label": "Videos and audio", "code": ""}, {"label": "Videos", "code": "video"},
                        {"label": "Audio", "code": "audio"}]
                value: page.kindFilter
                accessibleName: "Type"
                toolTipText: "Show videos, audio, or both"
                onActivated: { page.kindFilter = currentValue; page.applyFilters() }
            }
            StyledComboBox {
                Layout.preferredWidth: 170
                model: libraryController.siteOptions
                value: page.siteFilter
                accessibleName: "Site"
                toolTipText: "Show downloads from one site"
                onActivated: { page.siteFilter = currentValue; page.applyFilters() }
            }
            AppButton {
                text: "Play all"
                iconName: "play"
                toolTipText: "Play the songs (or, with Videos chosen, the videos) the list shows, newest first"
                enabled: libraryController.total > 0
                onClicked: page.playAll()
            }
            AppButton {
                kind: "ghost"
                iconName: "refresh"
                toolTipText: "Reload the list"
                onClicked: libraryController.reload()
            }
        }

        Timer { id: filterTimer; interval: 250; onTriggered: page.applyFilters() }

        Text {
            text: libraryController.total + (libraryController.total === 1 ? " download" : " downloads")
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            color: Theme.textMuted
        }

        ListView {
            id: view
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: libraryController.model
            spacing: 2
            reuseItems: true
            cacheBuffer: 600
            boundsBehavior: Flickable.StopAtBounds
            keyNavigationEnabled: true
            activeFocusOnTab: true
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Accessible.role: Accessible.List
            Accessible.name: "Library"
            Keys.onReturnPressed: page.play(libraryController.model.get(view.currentIndex).path)
            Keys.onDeletePressed: { var row = libraryController.model.get(view.currentIndex); libraryController.remove([row.historyId]) }

            delegate: Rectangle {
                id: record
                required property int index
                required property int historyId
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

                width: view.width
                height: 68
                radius: Theme.radius
                color: rowHover.hovered || ListView.isCurrentItem ? Theme.surfaceHover : "transparent"
                border.width: ListView.isCurrentItem && view.activeFocus ? 2 : 0
                border.color: Theme.focusRing
                Accessible.role: Accessible.ListItem
                Accessible.name: record.title + (record.missing ? ", file moved or deleted" : "")
                HoverHandler { id: rowHover }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spaceSm
                    anchors.rightMargin: Theme.spaceSm
                    spacing: Theme.spaceMd

                    Thumb {
                        Layout.preferredWidth: 88
                        Layout.preferredHeight: 50
                        source: record.thumbnail
                        kind: record.kind
                        opacity: record.missing ? 0.5 : 1
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3
                        Text {
                            Layout.fillWidth: true
                            text: record.title
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontBody
                            font.weight: Font.DemiBold
                            color: record.missing ? Theme.textMuted : Theme.text
                            elide: Text.ElideRight
                        }
                        Text {
                            Layout.fillWidth: true
                            text: record.missing ? "Moved or deleted: " + record.fileName
                                : [record.uploader, record.site, record.qualityText, record.durationText, record.sizeText,
                                   record.dateText].filter(part => part.length > 0).join("  ·  ")
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
                        toolTipText: "Play here (Enter)"
                        onClicked: page.play(record.path)
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
                        onClicked: menu.openFor(record.historyId, record.url, record.missing, record.kind, record.title)
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    z: -1
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: function (mouse) {
                        view.currentIndex = record.index
                        if (mouse.button === Qt.RightButton) menu.openFor(record.historyId, record.url, record.missing, record.kind, record.title)
                    }
                    onDoubleClicked: if (!record.missing) page.play(record.path)
                }
            }

            EmptyState {
                anchors.centerIn: parent
                visible: view.count === 0
                iconName: "library"
                title: search.text.length > 0 || page.kindFilter || page.siteFilter ? "No downloads match" : "No downloads yet"
                text: search.text.length > 0 || page.kindFilter || page.siteFilter ? "Try other search words or filters."
                    : "Finished downloads appear here, newest first."
            }
        }
    }

    AppMenu {
        id: menu
        property int historyId: -1
        property string url: ""
        property bool missing: false
        property string kind: ""
        property string videoTitle: ""
        function openFor(historyId, url, missing, kind, title) {
            menu.historyId = historyId
            menu.url = url
            menu.missing = missing
            menu.kind = kind
            menu.videoTitle = title
            menu.popup()
        }
        AppMenuItem {
            text: "Open in another player"
            enabled: !menu.missing
            onTriggered: appController.openPath(libraryController.pathOf(menu.historyId))
        }
        AppMenuItem {
            text: "Extract audio"
            enabled: !menu.missing && menu.kind === "video"
            onTriggered: extractDialog.forVideo(menu.historyId, menu.videoTitle)
        }
        AppMenuSeparator {}
        AppMenuItem { text: "Copy link"; enabled: menu.url.length > 0; onTriggered: appController.copyText(menu.url) }
        AppMenuItem { text: "Open link in browser"; enabled: menu.url.length > 0; onTriggered: appController.openUrl(menu.url) }
        AppMenuItem { text: "Download again"; enabled: menu.url.length > 0; onTriggered: libraryController.redownload(menu.historyId) }
        AppMenuSeparator {}
        AppMenuItem { text: "Remove from the library (keep the file)"; onTriggered: libraryController.remove([menu.historyId]) }
        AppMenuItem {
            text: "Move the file to the Recycle Bin"
            danger: true
            enabled: !menu.missing
            onTriggered: deleteDialog.open()
        }
    }

    ExtractAudioDialog { id: extractDialog }

    AppDialog {
        id: deleteDialog
        title: "Move to the Recycle Bin?"
        standardButtons: Dialog.Yes | Dialog.Cancel
        defaultButton: Dialog.Cancel
        width: 420
        onAccepted: libraryController.deleteFiles([menu.historyId])
        Text {
            width: parent.width
            text: "The file, with its captions and lyrics, goes to the Recycle Bin, where you can restore it, and leaves the library."
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.text
            wrapMode: Text.WordWrap
        }
    }
}
