// qmllint disable unqualified
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

import "../components"

// Paste a link and press Download, or the arrow on its right to choose formats and videos first. Below,
// the queue: every download with its progress, its buttons, and a menu of everything else.
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

    // Bumped as the list changes, so the selection bar's buttons re-check the picked rows.
    property int rowsRevision: 0
    readonly property var _rows: { page.rowsRevision; return page.allRows() }

    function allRows() {
        var rows = []
        for (var i = 0; i < queueController.model.count; ++i) rows.push(queueController.model.get(i))
        return rows
    }
    function selectRange(index) {
        var from = Math.min(selection.anchor < 0 ? index : selection.anchor, index)
        var to = Math.max(selection.anchor < 0 ? index : selection.anchor, index)
        selection.addRange(page._rows.slice(from, to + 1).map(row => row.jobId))
    }
    // True when any picked download allows this ("canPause", "canResume", "canRetry").
    function anyPicked(flag) {
        return page._rows.some(row => row[flag] === true && selection.contains(row.jobId))
    }
    function applyToPicked(action) {
        queueController.applyToJobs(action, selection.ids)
    }

    ListSelection { id: selection }

    Connections {
        target: queueController
        function onChanged() {
            page.rowsRevision += 1
            selection.keep(page._rows.map(row => row.jobId))
        }
    }

    function focusLink() {
        linkField.selectInput()
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
        var text = linkField.text
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
                toolTipText: "YouTube and every other site yt-dlp supports. Press Enter to download with the chosen preset."
                onAccepted: page.download()
                input.Keys.onEscapePressed: linkField.clear()
            }
            StyledComboBox {
                Layout.preferredWidth: 230
                model: prefsController.presets
                value: page.presetId
                accessibleName: "Preset"
                toolTipText: "How the Download button saves: the type, quality, and container"
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
        }

        SelectionBar {
            Layout.fillWidth: true
            visible: selection.count > 0
            count: selection.count
            total: queueView.count
            onSelectAllRequested: selection.setAll(page._rows.map(row => row.jobId))
            onClearRequested: selection.clear()

            AppButton {
                kind: "ghost"
                compact: true
                text: "Pause"
                iconName: "pause"
                enabled: page.anyPicked("canPause")
                toolTipText: "Pause the picked downloads; they continue from where they stopped"
                onClicked: page.applyToPicked("pause")
            }
            AppButton {
                kind: "ghost"
                compact: true
                text: "Resume"
                iconName: "play"
                enabled: page.anyPicked("canResume")
                onClicked: page.applyToPicked("resume")
            }
            AppButton {
                kind: "ghost"
                compact: true
                text: "Try again"
                iconName: "refresh"
                enabled: page.anyPicked("canRetry")
                toolTipText: "Try the picked failed or finished downloads again"
                onClicked: page.applyToPicked("retry")
            }
            AppButton {
                kind: "danger"
                compact: true
                text: "Remove"
                iconName: "delete"
                toolTipText: "Take the picked downloads off the list (Delete)"
                onClicked: page.removeJobs(selection.ids, selection.count + " downloads")
            }
        }

        // Above the list it acts on: finished downloads leave it, and the Library keeps their files.
        RowLayout {
            Layout.fillWidth: true
            visible: selection.count === 0 && queueController.finishedCount > 0
            spacing: Theme.spaceSm

            Text {
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

            // Ctrl+A picks every download, Ctrl+Space the current one, and Esc lets go of them.
            Keys.onPressed: function (event) {
                if (event.matches(StandardKey.SelectAll)) {
                    selection.setAll(page._rows.map(row => row.jobId))
                    event.accepted = true
                } else if (event.key === Qt.Key_Space && (event.modifiers & Qt.ControlModifier)) {
                    var current = queueController.model.get(queueView.currentIndex)
                    if (current.jobId !== undefined) selection.toggle(current.jobId, queueView.currentIndex)
                    event.accepted = true
                } else if (event.key === Qt.Key_Escape && selection.count > 0) {
                    selection.clear()
                    event.accepted = true
                }
            }
            Keys.onSpacePressed: {
                var row = queueController.model.get(queueView.currentIndex)
                if (row.canPause) queueController.pause(row.jobId)
                else if (row.canResume || row.canRetry) queueController.resume(row.jobId)
            }
            Keys.onDeletePressed: {
                if (selection.count > 0) {
                    page.removeJobs(selection.ids, selection.count + " downloads")
                    return
                }
                var row = queueController.model.get(queueView.currentIndex)
                if (row.jobId !== undefined) page.removeJob(row.jobId, row.title)
            }
            Keys.onMenuPressed: {
                var row = queueController.model.get(queueView.currentIndex)
                if (row.jobId !== undefined) jobMenu.openFor(row.jobId)
            }

            delegate: JobItem {
                id: jobRow
                width: queueView.width
                current: ListView.isCurrentItem
                selected: selection.contains(jobRow.jobId)
                selecting: selection.count > 0
                onSelectToggled: function (jobId, index) { selection.toggle(jobId, index) }
                onRangeRequested: function (index) { page.selectRange(index) }
                onMenuRequested: function (jobId) { jobMenu.openFor(jobId) }
                onItemsRequested: function (jobId, title) { itemsDialog.show(jobId, title) }
                onFixRequested: function (jobId, action) {
                    if (action === "signin") page.openSignIns()
                    else if (action === "choose_folder") { folderDialog.jobId = jobId; folderDialog.open() }
                    else toolsController.updateAll()
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

        function openFor(jobId) {
            jobMenu.jobId = jobId
            for (var i = 0; i < queueController.model.count; ++i) {
                var row = queueController.model.get(i)
                if (row.jobId === jobId) { jobMenu.row = row; break }
            }
            jobMenu.popup()
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
        AppMenuItem { text: "Try again"; enabled: jobMenu.row.canRetry === true; onTriggered: queueController.retry(jobMenu.jobId) }
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

    AppDialog {
        id: itemsDialog
        property var items: []
        function show(jobId, title) {
            itemsDialog.title = title
            itemsDialog.items = queueController.items(jobId)
            itemsDialog.open()
        }
        standardButtons: Dialog.Close
        defaultButton: Dialog.Close
        width: Math.min(page.width - 2 * Theme.spaceXl, 640)

        ListView {
            width: parent.width
            implicitHeight: Math.min(contentHeight, 420)
            clip: true
            model: itemsDialog.items
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            delegate: RowLayout {
                id: itemRow
                required property var modelData
                width: ListView.view.width
                spacing: Theme.spaceSm
                Text {
                    Layout.preferredWidth: 36
                    text: itemRow.modelData.index
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontCaption
                    color: Theme.textMuted
                    horizontalAlignment: Text.AlignRight
                }
                Text {
                    Layout.fillWidth: true
                    text: itemRow.modelData.title
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontBody
                    color: Theme.text
                    elide: Text.ElideRight
                }
                StatusBadge {
                    text: itemRow.modelData.state === "done" ? "Saved"
                        : itemRow.modelData.state === "skipped" ? (itemRow.modelData.message || "Skipped") : "Waiting"
                    iconName: itemRow.modelData.state === "done" ? "completed"
                        : itemRow.modelData.state === "skipped" ? "skip" : "clock"
                    tone: itemRow.modelData.state === "done" ? "success"
                        : itemRow.modelData.state === "skipped" ? "warning" : "neutral"
                }
            }
        }
    }

    FolderDialog {
        id: folderDialog
        property int jobId: -1
        title: "Choose the download folder"
        onAccepted: {
            var path = appController.localPath(selectedFolder.toString())
            if (path.length > 0) {
                prefsController.saveSettings({"downloads.folder": path})
                if (folderDialog.jobId >= 0) queueController.moveToFolder(folderDialog.jobId, path)
            }
        }
    }
}
