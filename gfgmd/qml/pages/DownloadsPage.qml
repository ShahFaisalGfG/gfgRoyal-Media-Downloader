// qmllint disable unqualified
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQml.Models

import "../components"
import "../components/ListMenu.js" as ListMenu

// Paste a link and press Download, or the arrow on its right to choose formats and videos first. Below,
// the queue: every download with its progress, its buttons, and a menu of everything else; a playlist
// lists its videos under it, each with how it is doing.
Item {
    id: page

    signal openPreferences()
    signal openSignIns()

    property bool optionsOpen: false
    // The download options show (or are being read): the Download button's cap points up.
    readonly property bool optionsShown: page.optionsOpen && (analyzeController.busy || analyzeController.hasResult)
    readonly property string presetId: { prefsController.revision; return prefsController.value("downloads.preset") }

    // Downloads that saved nothing and are finished (cancelled, failed, already downloaded) go at
    // once, with their unfinished parts; any in progress or with saved files asks first.
    function removeJobs(jobIds, name) {
        var removal = queueController.removal(jobIds)
        if (removal.inProgress === 0 && removal.savedFiles === 0) {
            queueController.applyToJobs("remove", jobIds)
            selection.clear()
        } else {
            removeDialog.show(jobIds, name, removal)
        }
    }
    function removeJob(jobId, title) {
        page.removeJobs([jobId], title)
    }

    // ── Picking several downloads ────────────────────────────────────────

    // Downloads are picked, not the videos listed under a playlist. The list changes four times a
    // second while downloading, so the selection is checked only when rows leave it.
    function jobIds(from, to) {
        var ids = []
        var first = from === undefined ? 0 : from
        var last = to === undefined ? queueController.model.count - 1 : to
        for (var i = first; i <= last; ++i) {
            var row = queueController.model.get(i)
            if (row.rowType === "job") ids.push(row.jobId)
        }
        return ids
    }
    function selectRange(index) {
        var from = Math.min(selection.anchor < 0 ? index : selection.anchor, index)
        var to = Math.max(selection.anchor < 0 ? index : selection.anchor, index)
        selection.addRange(page.jobIds(from, to))
    }
    // What the picked downloads allow, asked again as the queue changes.
    readonly property var picked: {
        queueController.runningCount  // re-read on every change of the queue
        return selection.count > 0 ? queueController.pickedFlags(selection.ids) : ({})
    }
    function applyToPicked(action) {
        queueController.applyToJobs(action, selection.ids)
    }

    ListSelection { id: selection }

    Connections {
        target: queueController.model
        function onRowsRemoved() { if (selection.count > 0) selection.keep(page.jobIds()) }
        function onModelReset() { if (selection.count > 0) selection.keep(page.jobIds()) }
    }

    function focusLink() {
        linkField.selectInput()
    }

    // Play one saved video of a playlist, with the playlist's other saved videos for Previous and Next.
    function playFrom(jobId, path) {
        playerController.playFrom(path, queueController.savedFiles(jobId))
    }

    function pasteLink() {
        linkField.pasteClipboard()
    }

    // Every link in the box (a paste of several keeps them all); an empty box takes the clipboard's.
    function download() {
        if (linkField.links.length === 0) page.pasteLink()
        if (linkField.links.length > 0 && queueController.addLinks(linkField.links.join("\n"), page.presetId) > 0)
            linkField.clear()
    }

    // The download options read one link: the one in the box.
    function showOptions() {
        if (linkField.text.length === 0) page.pasteLink()
        var text = linkField.links.length > 0 ? linkField.links[0] : ""
        if (text.length === 0) {
            appController.notice("Paste a link first, then open its download options.")
            return
        }
        page.optionsOpen = true
        analyzeController.analyze(text)
    }
    function toggleOptions() {
        if (page.optionsShown) page.optionsOpen = false
        else page.showOptions()
    }

    // Put a link in the link box and open its download options (the Sign-ins page's library shortcuts).
    function openLink(url) {
        linkField.setLinks(url)
        page.showOptions()
    }

    function addDropped(text) {
        if (queueController.addLinks(text, page.presetId) === 0)
            linkField.setLinks(text)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spaceXl
        spacing: Theme.spaceLg

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm

            LinkField {
                id: linkField
                Layout.fillWidth: true
                placeholderText: "Paste a link to a video, playlist, or channel"
                toolTipText: "Works with YouTube and many other sites. Press Enter to download with the choice on the right."
                onAccepted: page.download()
                onNotLink: appController.notice("The copied text isn't a link. Copy the link from your browser's address bar.")
                input.Keys.onEscapePressed: linkField.clear()
            }
            StyledComboBox {
                Layout.preferredWidth: 230
                model: prefsController.presets
                value: page.presetId
                accessibleName: "Preset"
                toolTipText: "What the Download button saves: video or audio, its quality, and the file type"
                onActivated: prefsController.saveSettings({"downloads.preset": currentValue})
            }
            // Download with the preset, or open the cap for this link's download options.
            SplitButton {
                enabled: toolsController.ready
                text: "Download"
                iconName: "download"
                toolTipText: toolsController.ready ? "Download with the chosen preset (Enter)"
                    : "Get the download tools first"
                capToolTipText: "Download options: pick the quality, format, subtitles, and which videos (Ctrl+Shift+O)"
                capOpen: page.optionsShown
                capAccessibleName: page.optionsShown ? "Close the download options" : "Open the download options"
                onClicked: page.download()
                onCapClicked: page.toggleOptions()
            }
        }

        ToolsCard {
            Layout.fillWidth: true
            visible: !toolsController.ready
            onChooseLocations: page.openPreferences()
        }

        WarningNotice {
            Layout.fillWidth: true
            visible: analyzeController.error.length > 0
            iconName: "error"
            text: analyzeController.error
            AppButton {
                visible: analyzeController.errorAction === "signin"
                text: "Sign in"
                iconName: "key"
                toolTipText: "Sign in to " + analyzeController.siteLabel + " so its private or age-restricted videos can download"
                onClicked: page.openSignIns()
            }
            AppButton {
                visible: analyzeController.errorAction === "repair_tools" || analyzeController.errorAction === "update_tools"
                text: "Update tools"
                iconName: "repair"
                onClicked: toolsController.updateAll()
            }
            AppButton {
                kind: "ghost"
                compact: true
                iconName: "close"
                toolTipText: "Dismiss"
                onClicked: analyzeController.clear()
            }
        }

        OptionsPanel {
            Layout.fillWidth: true
            visible: page.optionsShown
            maxHeight: Math.max(240, page.height * 0.62)
            presetId: page.presetId
            onClosed: page.optionsOpen = false
            onQueued: linkField.clear()
        }

        SelectionBar {
            Layout.fillWidth: true
            visible: selection.count > 0
            count: selection.count
            total: queueController.jobCount
            onSelectAllRequested: selection.setAll(page.jobIds())
            onClearRequested: selection.clear()

            AppButton {
                kind: "ghost"
                compact: true
                text: "Pause"
                iconName: "pause"
                enabled: page.picked.canPause === true
                toolTipText: "Pause the picked downloads; they continue from where they stopped"
                onClicked: page.applyToPicked("pause")
            }
            AppButton {
                kind: "ghost"
                compact: true
                text: "Resume"
                iconName: "play"
                enabled: page.picked.canResume === true
                onClicked: page.applyToPicked("resume")
            }
            AppButton {
                kind: "ghost"
                compact: true
                text: "Try again"
                iconName: "refresh"
                enabled: page.picked.canRetry === true
                toolTipText: "Try the picked failed or finished downloads again"
                onClicked: page.applyToPicked("retry")
            }
            AppButton {
                kind: "danger"
                compact: true
                text: "Remove"
                iconName: "delete"
                toolTipText: "Take the picked downloads off the list (Delete)"
                onClicked: page.removeJobs(selection.ids, selection.count === 1 ? "1 download" : selection.count + " downloads")
            }
        }

        // Above the list it acts on: finished downloads leave it, and the Library keeps their files.
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.controlHeight + Theme.spaceSm
            visible: selection.count === 0 && queueController.finishedCount > 0
            spacing: Theme.spaceSm

            Text {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                text: queueController.finishedCount === 1 ? "1 finished download" : queueController.finishedCount + " finished downloads"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.textMuted
                elide: Text.ElideRight
            }
            AppButton {
                kind: "ghost"
                compact: true
                text: "Clear finished"
                iconName: "clear"
                toolTipText: "Take finished and cancelled downloads off this list; their files stay in the Library"
                onClicked: queueController.clearFinished()
            }
        }

        ListView {
            id: queueView
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: queueController.model
            spacing: 2
            reuseItems: true
            cacheBuffer: 600
            boundsBehavior: Flickable.StopAtBounds
            keyNavigationEnabled: true
            activeFocusOnTab: true
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Accessible.role: Accessible.List
            Accessible.name: "Downloads"

            // Ctrl+A picks every download, Ctrl+Space the current one, and Esc lets go of them. On a
            // playlist, Right shows its videos and Left hides them (from one of them, too).
            Keys.onPressed: function (event) {
                var current = queueController.model.get(queueView.currentIndex)
                if (event.matches(StandardKey.SelectAll)) {
                    selection.setAll(page.jobIds())
                    event.accepted = true
                } else if (event.key === Qt.Key_Space && (event.modifiers & Qt.ControlModifier)) {
                    if (current.rowType === "job") selection.toggle(current.jobId, queueView.currentIndex)
                    event.accepted = true
                } else if (event.key === Qt.Key_Escape && selection.count > 0) {
                    selection.clear()
                    event.accepted = true
                } else if (event.key === Qt.Key_Right && current.rowType === "job" && current.entryCount > 0) {
                    queueController.setExpanded(current.jobId, true)
                    event.accepted = true
                } else if (event.key === Qt.Key_Left && current.jobId !== undefined
                           && (current.rowType === "entry" || current.expanded)) {
                    var jobId = current.jobId
                    queueController.setExpanded(jobId, false)
                    queueView.currentIndex = queueController.model.rowOf("j" + jobId)
                    event.accepted = true
                }
            }
            Keys.onSpacePressed: {
                var row = queueController.model.get(queueView.currentIndex)
                if (row.rowType === "entry") {
                    if (row.lastFile) page.playFrom(row.jobId, row.lastFile)
                } else if (row.canPause) queueController.pause(row.jobId)
                else if (row.canRetry) queueController.retry(row.jobId)
                else if (row.canResume) queueController.resume(row.jobId)
            }
            Keys.onDeletePressed: {
                if (selection.count > 0) {
                    page.removeJobs(selection.ids, selection.count === 1 ? "1 download" : selection.count + " downloads")
                    return
                }
                var row = queueController.model.get(queueView.currentIndex)
                if (row.rowType === "job") page.removeJob(row.jobId, row.title)
            }
            // The Menu key and Shift+F10 (a context-menu request on Windows) open the current row's menu.
            ContextMenu.onRequested: function (position) {
                var index = ListMenu.rowFor(queueView, position)
                if (index < 0) return
                queueView.currentIndex = index
                queueView.openMenu()
            }
            // The current row's menu, opened at the row.
            function openMenu() {
                var row = queueController.model.get(queueView.currentIndex)
                if (row.rowType === "job") jobMenu.openFor(row.jobId, queueView.currentItem)
                else if (row.rowType === "entry") entryMenu.openFor(row, queueView.currentItem)
            }

            delegate: DelegateChooser {
                role: "rowType"

                DelegateChoice {
                    roleValue: "job"

                    JobItem {
                        id: jobRow
                        width: queueView.width
                        current: ListView.isCurrentItem
                        selected: selection.contains(jobRow.jobId)
                        selecting: selection.count > 0
                        onSelectToggled: function (jobId, index) { selection.toggle(jobId, index) }
                        onRangeRequested: function (index) { page.selectRange(index) }
                        onMenuRequested: function (jobId) { jobMenu.openFor(jobId) }
                        onExpandToggled: function (jobId, expanded) { queueController.setExpanded(jobId, expanded) }
                        onPlayAllRequested: function (jobId) {
                            var files = queueController.savedFiles(jobId)
                            if (files.length > 0) playerController.playFrom(files[0], files)
                        }
                        onFixRequested: function (jobId, action) {
                            if (action === "signin") page.openSignIns()
                            else if (action === "choose_folder") {
                                folderDialog.jobId = jobId
                                folderDialog.audio = jobRow.kind === "audio"
                                folderDialog.open()
                            }
                            else {
                                toolsController.updateAll()
                                appController.notice("Updating the download tools. Downloads that needed them try again when it's done.")
                            }
                        }
                    }
                }
                DelegateChoice {
                    roleValue: "entry"

                    EntryItem {
                        id: entryRow
                        width: queueView.width
                        current: ListView.isCurrentItem
                        onMenuRequested: function (jobId, itemId) {
                            entryMenu.openFor(queueController.model.get(entryRow.index))
                        }
                        onPlayRequested: function (jobId, path) { page.playFrom(jobId, path) }
                    }
                }
            }

            EmptyState {
                anchors.centerIn: parent
                visible: queueView.count === 0
                iconName: "download"
                title: "Nothing downloading yet"
                text: "Copy a link from your browser and press Download, or drag links onto this window. "
                    + "Playlists and channels download whole; the arrow beside Download picks the videos, quality, and subtitles."
            }
        }
    }

    AppMenu {
        id: jobMenu
        property int jobId: -1
        property var row: ({})
        readonly property bool hasLink: (jobMenu.row.url || "").length > 0

        function openFor(jobId, at) {
            jobMenu.jobId = jobId
            jobMenu.row = queueController.model.get(queueController.model.rowOf("j" + jobId))
            jobMenu.openAt(at || null)
        }

        AppMenuItem { text: "Open folder"; onTriggered: appController.openPath(jobMenu.row.folder) }
        AppMenuItem { text: "Copy link"; enabled: jobMenu.hasLink; onTriggered: appController.copyText(jobMenu.row.url) }
        AppMenuItem {
            text: "Open link in browser"
            enabled: jobMenu.hasLink
            onTriggered: appController.openUrl(jobMenu.row.url)
        }
        AppMenuSeparator {}
        AppMenuItem { text: "Move up"; onTriggered: queueController.move(jobMenu.jobId, -1) }
        AppMenuItem { text: "Move down"; onTriggered: queueController.move(jobMenu.jobId, 1) }
        AppMenuSeparator {}
        AppMenuItem { text: "Pause"; enabled: jobMenu.row.canPause === true; onTriggered: queueController.pause(jobMenu.jobId) }
        AppMenuItem { text: "Resume"; enabled: jobMenu.row.canResume === true; onTriggered: queueController.resume(jobMenu.jobId) }
        AppMenuItem {
            // On a finished download it fetches only what was skipped (a private video, one that kept failing).
            text: jobMenu.row.jobState === "done"
                ? "Try the skipped " + (jobMenu.row.kind === "audio" ? "songs" : "videos") + " again" : "Try again"
            enabled: jobMenu.row.canRetry === true
            onTriggered: queueController.retry(jobMenu.jobId)
        }
        AppMenuItem {
            text: "Download again"
            enabled: jobMenu.row.canRedownload === true
            onTriggered: queueController.downloadAgain(jobMenu.jobId)
        }
        AppMenuItem {
            text: "Cancel and delete unfinished files"
            danger: true
            enabled: jobMenu.row.canPause === true || jobMenu.row.jobState === "paused"
            onTriggered: queueController.cancel(jobMenu.jobId)
        }
        AppMenuSeparator {}
        AppMenuItem {
            text: "Extract audio"
            visible: jobMenu.row.kind !== "audio"
            enabled: jobMenu.row.jobState === "done" && (jobMenu.row.lastFile || "").length > 0
            onTriggered: extractDialog.forJob(jobMenu.jobId, jobMenu.row.title)
        }
        AppMenuItem { text: "Remove"; onTriggered: page.removeJob(jobMenu.jobId, jobMenu.row.title) }
    }

    ExtractAudioDialog { id: extractDialog }

    // Asks only when removing loses something: downloads in progress, or files they saved.
    AppDialog {
        id: removeDialog
        property var jobIds: []
        property int count: 0
        property int inProgress: 0
        property int savedFiles: 0
        readonly property bool many: removeDialog.count > 1
        function show(jobIds, name, removal) {
            removeDialog.jobIds = jobIds
            removeDialog.count = removal.count
            removeDialog.inProgress = removal.inProgress
            removeDialog.savedFiles = removal.savedFiles
            removeName.text = name
            deleteFiles.checked = false
            removeDialog.open()
        }
        title: removeDialog.many ? "Remove " + removeDialog.count + " downloads?"
            : removeDialog.inProgress > 0 ? "Remove this unfinished download?" : "Remove this download?"
        standardButtons: Dialog.Ok | Dialog.Cancel
        defaultButton: Dialog.Ok
        width: Math.min(page.width - 2 * Theme.spaceXl, 460)
        Component.onCompleted: removeDialog.standardButton(Dialog.Ok).text = "Remove"
        onAccepted: {
            queueController.applyToJobs(removeDialog.savedFiles > 0 && deleteFiles.checked ? "remove_saved" : "remove",
                                        removeDialog.jobIds)
            selection.clear()
        }

        ColumnLayout {
            width: parent.width
            spacing: Theme.spaceSm

            Text {
                textFormat: Text.PlainText
                id: removeName
                Layout.fillWidth: true
                visible: !removeDialog.many  // the title already counts them
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                font.weight: Font.DemiBold
                color: Theme.text
                wrapMode: Text.WordWrap
                maximumLineCount: 3
                elide: Text.ElideRight
            }
            Text {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                text: {
                    var unfinished = !removeDialog.many
                        ? (removeDialog.inProgress > 0 ? "It leaves the list unfinished, and what it downloaded so far is deleted."
                                                       : "It leaves the list.")
                        : removeDialog.inProgress === 0 ? "They leave the list."
                        : (removeDialog.inProgress === removeDialog.count ? "They leave the list unfinished"
                           : removeDialog.inProgress + " of them leave the list unfinished")
                          + ", and what they downloaded so far is deleted."
                    var saved = removeDialog.savedFiles === 0 ? ""
                        : removeDialog.savedFiles === 1 ? " The file " + (removeDialog.many ? "they" : "it") + " saved stays in the folder and the Library."
                        : " The " + removeDialog.savedFiles + " files " + (removeDialog.many ? "they" : "it")
                          + " saved stay in the folder and the Library."
                    return unfinished + saved
                }
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                color: Theme.text
                wrapMode: Text.WordWrap
            }
            CheckBox {
                id: deleteFiles
                Layout.leftMargin: -Theme.spaceSm
                visible: removeDialog.savedFiles > 0
                text: removeDialog.savedFiles === 1 ? "Also move the saved file to the Recycle Bin"
                                                    : "Also move the saved files to the Recycle Bin"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
            }
            Text {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                visible: deleteFiles.visible
                text: removeDialog.savedFiles === 1 ? "You can restore it from the Recycle Bin; its captions and lyrics go with it."
                                                    : "You can restore them from the Recycle Bin; their captions and lyrics go with them."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.textMuted
                wrapMode: Text.WordWrap
            }
        }
    }

    // A playlist video's menu: play it, find it, or open its page.
    AppMenu {
        id: entryMenu
        property var row: ({})
        readonly property string file: entryMenu.row.lastFile || ""
        readonly property string link: entryMenu.row.url || ""

        function openFor(row, at) {
            entryMenu.row = row
            entryMenu.openAt(at || null)
        }

        AppMenuItem {
            text: "Play"
            enabled: entryMenu.file.length > 0
            onTriggered: page.playFrom(entryMenu.row.jobId, entryMenu.file)
        }
        AppMenuItem {
            text: "Show in folder"
            enabled: entryMenu.file.length > 0
            onTriggered: appController.revealFile(entryMenu.file)
        }
        AppMenuSeparator {}
        AppMenuItem { text: "Copy link"; enabled: entryMenu.link.length > 0; onTriggered: appController.copyText(entryMenu.link) }
        AppMenuItem {
            text: "Open link in browser"
            enabled: entryMenu.link.length > 0
            onTriggered: appController.openUrl(entryMenu.link)
        }
    }

    // A download that couldn't save picks another folder: it becomes the folder for its type (as in
    // Preferences), and the download goes on there.
    FolderDialog {
        id: folderDialog
        property int jobId: -1
        property bool audio: false
        title: folderDialog.audio ? "Choose the audio folder" : "Choose the video folder"
        onAccepted: {
            var path = appController.localPath(selectedFolder.toString())
            if (path.length > 0) {
                prefsController.saveSettings(folderDialog.audio ? {"downloads.audio_folder": path} : {"downloads.folder": path})
                if (folderDialog.jobId >= 0) queueController.moveToFolder(folderDialog.jobId, path)
                appController.notice((folderDialog.audio ? "Songs" : "Videos") + " now save in " + path + ".")
            }
        }
    }
}
