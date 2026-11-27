// qmllint disable unqualified
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQml.Models

import "../components"
import "../components/ListMenu.js" as ListMenu

// Everything downloaded, newest first: search, filter by type and site, play or view, show in folder,
// download again, or move files to the Recycle Bin. A playlist's or channel's files make one group
// row that opens into them, in the playlist's order.
Item {
    id: page

    property string kindFilter: ""
    property string siteFilter: ""

    function applyFilters() {
        selection.clear()  // picked rows the new filters hide would be acted on unseen
        libraryController.setFilters(search.text, page.kindFilter, page.siteFilter)
    }
    // Play in the built-in players; the list as filtered gives them Previous and Next, or, for a file
    // inside a playlist group, the rest of that playlist in order.
    function play(path, groupKey) {
        playerController.playFrom(path, groupKey ? libraryController.groupPaths(groupKey) : libraryController.playlist())
    }
    function playGroup(groupKey) {
        var list = libraryController.groupPaths(groupKey)
        if (list.length > 0) playerController.playFrom(list[0], list)
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
        for (var i = from; i <= to; ++i) {
            var row = libraryController.model.get(i)
            if (row.rowType === "group") ids = ids.concat(libraryController.groupIds(row.groupKey))
            else ids.push(row.historyId)
        }
        selection.addRange(ids)
    }
    // A group is picked when all its files are; its mark picks or lets go of them together.
    function groupPicked(groupKey) {
        var ids = libraryController.groupIds(groupKey)
        return ids.length > 0 && ids.every(id => selection.contains(id))
    }
    function toggleGroup(groupKey, index) {
        var ids = libraryController.groupIds(groupKey)
        if (page.groupPicked(groupKey)) selection.drop(ids)
        else selection.addRange(ids)
        selection.anchor = index
    }
    function selectAll() {
        selection.setAll(libraryController.allIds())
    }
    // Take files off the library (they stay on disk), asking first when it is more than one.
    function removeFiles(ids) {
        if (ids.length > 1) {
            removeDialog.ask(ids)
            return
        }
        libraryController.remove(ids)
        selection.clear()
    }
    function removePicked() {
        page.removeFiles(selection.ids)
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
                accessibleName: "Search the library"
                onTextChanged: filterTimer.restart()
            }
            StyledComboBox {
                Layout.preferredWidth: 150
                model: [{"label": "All files", "code": ""}, {"label": "Videos", "code": "video"},
                        {"label": "Audio", "code": "audio"}, {"label": "Pictures", "code": "photo"}]
                value: page.kindFilter
                accessibleName: "Type"
                onActivated: { page.kindFilter = currentValue; page.applyFilters() }
            }
            StyledComboBox {
                Layout.preferredWidth: 170
                model: libraryController.siteOptions
                value: page.siteFilter
                accessibleName: "Site"
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
            textFormat: Text.PlainText
            visible: selection.count === 0
            text: libraryController.total + (libraryController.total === 1 ? " file" : " files")
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
                onClicked: page.playList(libraryController.pathsOf(selection.ids))
            }
            AppButton {
                kind: "ghost"
                compact: true
                text: "Extract audio"
                iconName: "audio"
                onClicked: extractDialog.forVideos(selection.ids, selection.count === 1 ? "1 file" : selection.count + " files")
            }
            AppButton {
                kind: "ghost"
                compact: true
                text: "Remove"
                iconName: "clear"
                toolTipText: "Takes them off the library; the files stay on this PC"
                onClicked: page.removePicked()
            }
            AppButton {
                kind: "danger"
                compact: true
                text: "Recycle Bin"
                iconName: "delete"
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
            // The Menu key and Shift+F10 (a context-menu request on Windows) open the current row's menu, at the row.
            ContextMenu.onRequested: function (position) {
                var index = ListMenu.rowFor(view, position)
                if (index < 0) return
                view.currentIndex = index
                var current = libraryController.model.get(index)
                if (current.rowType === "group")
                    groupMenu.openFor(current.groupKey, current.title, current.kind, current.path, view.currentItem)
                else if (current.historyId !== undefined)
                    menu.openFor(current.historyId, current.url, current.missing, current.kind, current.title, view.currentItem)
            }
            // Enter plays (a group, all of it); Right opens a group and Left closes it (from a file in it, too).
            Keys.onReturnPressed: {
                var row = libraryController.model.get(view.currentIndex)
                if (row.rowType === "group") page.playGroup(row.groupKey)
                else if (row.path) page.play(row.path, row.groupKey)
            }
            Keys.onDeletePressed: {
                if (selection.count > 0) {
                    page.removePicked()
                    return
                }
                var row = libraryController.model.get(view.currentIndex)
                if (row.rowType === "group") page.removeFiles(libraryController.groupIds(row.groupKey))
                else if (row.historyId !== undefined) page.removeFiles([row.historyId])
            }
            // Ctrl+A picks every file the filters show, Ctrl+Space the current one, and Esc lets go.
            Keys.onPressed: function (event) {
                var current = libraryController.model.get(view.currentIndex)
                if (event.matches(StandardKey.SelectAll)) {
                    page.selectAll()
                    event.accepted = true
                } else if (event.key === Qt.Key_Space && (event.modifiers & Qt.ControlModifier)) {
                    if (current.rowType === "group") page.toggleGroup(current.groupKey, view.currentIndex)
                    else if (current.historyId !== undefined) selection.toggle(current.historyId, view.currentIndex)
                    event.accepted = true
                } else if (event.key === Qt.Key_Escape && selection.count > 0) {
                    selection.clear()
                    event.accepted = true
                } else if (event.key === Qt.Key_Right && current.rowType === "group" && !current.expanded) {
                    libraryController.setExpanded(current.groupKey, true)
                    event.accepted = true
                } else if (event.key === Qt.Key_Left && current.groupKey && (current.rowType === "file" || current.expanded)) {
                    var key = current.groupKey
                    libraryController.setExpanded(key, false)
                    view.currentIndex = libraryController.model.rowOf("g:" + key)
                    event.accepted = true
                }
            }

            delegate: DelegateChooser {
                role: "rowType"

                DelegateChoice {
                    roleValue: "group"

                    LibraryGroupItem {
                        id: groupRow
                        width: view.width
                        current: ListView.isCurrentItem
                        selected: { selection.ids; return page.groupPicked(groupRow.groupKey) }
                        selecting: selection.count > 0
                        onExpandToggled: function (groupKey, expanded) { libraryController.setExpanded(groupKey, expanded) }
                        onPlayAllRequested: function (groupKey) { page.playGroup(groupKey) }
                        onMenuRequested: function (groupKey, title, kind, folder) { groupMenu.openFor(groupKey, title, kind, folder) }
                        onSelectToggled: function (groupKey, index) { page.toggleGroup(groupKey, index) }
                        onRangeRequested: function (index) { page.selectRange(index) }
                    }
                }
                DelegateChoice {
                    roleValue: "file"

                    LibraryFileItem {
                        id: fileRow
                        width: view.width
                        current: ListView.isCurrentItem
                        selected: selection.contains(fileRow.historyId)
                        selecting: selection.count > 0
                        onPlayRequested: function (path, groupKey) { page.play(path, groupKey) }
                        onMenuRequested: function (historyId, url, missing, kind, title) {
                            menu.openFor(historyId, url, missing, kind, title)
                        }
                        onSelectToggled: function (historyId, index) { selection.toggle(historyId, index) }
                        onRangeRequested: function (index) { page.selectRange(index) }
                    }
                }
            }

            EmptyState {
                anchors.centerIn: parent
                visible: view.count === 0
                iconName: "library"
                title: search.text.length > 0 || page.kindFilter || page.siteFilter ? "No files match" : "No files yet"
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
        function openFor(historyId, url, missing, kind, title, at) {
            menu.historyId = historyId
            menu.url = url
            menu.missing = missing
            menu.kind = kind
            menu.videoTitle = title
            menu.openAt(at || null)
        }
        AppMenuItem {
            text: menu.kind === "photo" ? "Open in another app" : "Open in another player"
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

    // A playlist's or channel's group: play it, find its folder, extract its videos' sound, or let it go.
    AppMenu {
        id: groupMenu
        property string groupKey: ""
        property string groupTitle: ""
        property string kind: ""
        property string folder: ""
        function openFor(groupKey, title, kind, folder, at) {
            groupMenu.groupKey = groupKey
            groupMenu.groupTitle = title
            groupMenu.kind = kind
            groupMenu.folder = folder
            groupMenu.openAt(at || null)
        }
        AppMenuItem { text: groupMenu.kind === "photo" ? "View all" : "Play all"; onTriggered: page.playGroup(groupMenu.groupKey) }
        AppMenuItem { text: "Open folder"; onTriggered: appController.openPath(groupMenu.folder) }
        AppMenuItem {
            text: "Extract audio"
            visible: groupMenu.kind === "video"
            onTriggered: extractDialog.forVideos(libraryController.groupIds(groupMenu.groupKey), groupMenu.groupTitle)
        }
        AppMenuSeparator {}
        AppMenuItem {
            text: "Remove from the library (keep the files)"
            onTriggered: libraryController.remove(libraryController.groupIds(groupMenu.groupKey))
        }
        AppMenuItem {
            text: "Move the files to the Recycle Bin"
            danger: true
            onTriggered: deleteDialog.ask(libraryController.groupIds(groupMenu.groupKey))
        }
    }

    ExtractAudioDialog { id: extractDialog }

    AppDialog {
        id: removeDialog
        property var ids: []
        function ask(ids) {
            removeDialog.ids = ids
            removeDialog.open()
        }
        title: "Remove " + removeDialog.ids.length + " files from the library?"
        standardButtons: Dialog.Ok | Dialog.Cancel
        defaultButton: Dialog.Ok
        width: 420
        onAccepted: {
            libraryController.remove(removeDialog.ids)
            selection.clear()
        }
        Component.onCompleted: removeDialog.standardButton(Dialog.Ok).text = "Remove"
        Text {
            textFormat: Text.PlainText
            width: parent.width
            text: "They leave the library's list; the files stay where they are on your PC."
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.text
            wrapMode: Text.WordWrap
        }
    }

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
        Component.onCompleted: deleteDialog.standardButton(Dialog.Yes).text = "Move to Recycle Bin"
        Text {
            textFormat: Text.PlainText
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
