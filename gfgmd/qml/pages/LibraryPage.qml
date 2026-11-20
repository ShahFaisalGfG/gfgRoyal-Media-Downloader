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
        selection.clear()  // picked rows the new filters hide would be acted on unseen
        libraryController.setFilters(search.text, page.kindFilter, page.siteFilter)
    }
    // Play in the built-in players; the list as filtered gives them Previous and Next.
    function play(path) {
        playerController.playFrom(path, libraryController.playlist())
    }
    // Songs first (the audio bar plays them in a row), unless the list shows only videos.
    function playAll() {
        page.playList(libraryController.playlist())
    }
    function playList(list) {
        var wantAudio = page.kindFilter !== "video"
        var first = list.find(path => playerController.isAudio(path) === wantAudio) || list[0]
        if (first) playerController.playFrom(first, list)
    }

    // ── Picking several files ────────────────────────────────────────────

    function selectRange(index) {
        var from = Math.min(selection.anchor < 0 ? index : selection.anchor, index)
        var to = Math.max(selection.anchor < 0 ? index : selection.anchor, index)
        var ids = []
        for (var i = from; i <= to; ++i) ids.push(libraryController.model.get(i).historyId)
        selection.addRange(ids)
    }
    function selectAll() {
        selection.setAll(libraryController.allIds())
    }
    function removePicked() {
        libraryController.remove(selection.ids)
        selection.clear()
    }

    ListSelection { id: selection }

    // A picked file that leaves the library another way (its own menu, a new download replacing
    // its record) leaves the selection too, so the count stays true.
    Connections {
        target: libraryController
        function onChanged() {
            if (selection.count > 0) selection.keep(libraryController.allIds())
        }
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
            visible: selection.count === 0
            text: libraryController.total + (libraryController.total === 1 ? " download" : " downloads")
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            color: Theme.textMuted
        }

        SelectionBar {
            Layout.fillWidth: true
            visible: selection.count > 0
            count: selection.count
            total: libraryController.total
            onSelectAllRequested: page.selectAll()
            onClearRequested: selection.clear()

            AppButton {
                kind: "ghost"
                compact: true
                text: "Play"
                iconName: "play"
                toolTipText: "Play the picked files in the built-in players, newest first"
                onClicked: page.playList(libraryController.pathsOf(selection.ids))
            }
            AppButton {
                kind: "ghost"
                compact: true
                text: "Extract audio"
                iconName: "audio"
                toolTipText: "Save the picked videos' sound as songs (songs among them are left out)"
                onClicked: extractDialog.forVideos(selection.ids, selection.count === 1 ? "1 file" : selection.count + " files")
            }
            AppButton {
                kind: "ghost"
                compact: true
                text: "Remove"
                iconName: "clear"
                toolTipText: "Take the picked files off the library; the files stay (Delete)"
                onClicked: page.removePicked()
            }
            AppButton {
                kind: "danger"
                compact: true
                text: "Recycle Bin"
                iconName: "delete"
                toolTipText: "Move the picked files to the Recycle Bin"
                onClicked: deleteDialog.ask(selection.ids)
            }
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
            Keys.onDeletePressed: {
                if (selection.count > 0) {
                    page.removePicked()
                    return
                }
                var row = libraryController.model.get(view.currentIndex)
                libraryController.remove([row.historyId])
            }
            // Ctrl+A picks every file the filters show, Ctrl+Space the current one, and Esc lets go.
            Keys.onPressed: function (event) {
                if (event.matches(StandardKey.SelectAll)) {
                    page.selectAll()
                    event.accepted = true
                } else if (event.key === Qt.Key_Space && (event.modifiers & Qt.ControlModifier)) {
                    var current = libraryController.model.get(view.currentIndex)
                    if (current.historyId !== undefined) selection.toggle(current.historyId, view.currentIndex)
                    event.accepted = true
                } else if (event.key === Qt.Key_Escape && selection.count > 0) {
                    selection.clear()
                    event.accepted = true
                }
            }

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
                required property string format

                readonly property bool selected: selection.contains(record.historyId)

                width: view.width
                height: 68
                radius: Theme.radius
                color: record.selected ? Theme.accentSoft
                    : rowHover.hovered || ListView.isCurrentItem ? Theme.surfaceHover : "transparent"
                border.width: ListView.isCurrentItem && view.activeFocus ? 2 : 0
                border.color: Theme.focusRing
                Accessible.role: Accessible.ListItem
                Accessible.name: record.title + (record.kind === "audio" ? ", audio" : ", video")
                    + (record.missing ? ", file moved or deleted" : "")
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
                        label: record.format
                        opacity: record.missing ? 0.5 : 1

                        SelectMark {
                            checked: record.selected
                            shown: selection.count > 0 || rowHover.hovered
                            itemName: record.title
                            onToggled: selection.toggle(record.historyId, record.index)
                        }
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
                        else if (mouse.modifiers & Qt.ControlModifier) selection.toggle(record.historyId, record.index)
                        else if (mouse.modifiers & Qt.ShiftModifier) page.selectRange(record.index)
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
            visible: menu.kind === "video"
            enabled: !menu.missing
            onTriggered: extractDialog.forVideos([menu.historyId], menu.videoTitle)
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
            onTriggered: deleteDialog.ask([menu.historyId])
        }
    }

    ExtractAudioDialog { id: extractDialog }

    AppDialog {
        id: deleteDialog
        property var ids: []
        function ask(ids) {
            deleteDialog.ids = ids
            deleteDialog.open()
        }
        title: deleteDialog.ids.length > 1 ? "Move " + deleteDialog.ids.length + " files to the Recycle Bin?"
                                           : "Move to the Recycle Bin?"
        standardButtons: Dialog.Yes | Dialog.Cancel
        defaultButton: Dialog.Cancel
        width: 420
        onAccepted: {
            libraryController.deleteFiles(deleteDialog.ids)
            selection.clear()
        }
        Text {
            width: parent.width
            text: deleteDialog.ids.length > 1
                ? "The files, with their captions and lyrics, go to the Recycle Bin, where you can restore them, and leave the library."
                : "The file, with its captions and lyrics, goes to the Recycle Bin, where you can restore it, and leaves the library."
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.text
            wrapMode: Text.WordWrap
        }
    }
}
