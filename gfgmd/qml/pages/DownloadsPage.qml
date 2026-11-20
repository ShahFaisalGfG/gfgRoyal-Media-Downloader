// qmllint disable unqualified
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

import "../components"

// Paste a link and press Download, or open Options to choose formats and videos first. Below,
// the queue: every download with its progress, its buttons, and a menu of everything else.
Item {
    id: page

    signal openPreferences()
    signal openSignIns()

    property bool optionsOpen: false
    readonly property string presetId: { prefsController.revision; return prefsController.value("downloads.preset") }

    function focusLink() {
        linkField.selectInput()
    }

    function pasteLink() {
        var text = appController.clipboardText().trim()
        if (text.length > 0) linkField.text = text
        linkField.input.forceActiveFocus()
    }

    function download() {
        var text = linkField.text.trim()
        if (text.length === 0) {
            page.pasteLink()
            text = linkField.text.trim()
        }
        if (text.length > 0 && queueController.addLinks(text, page.presetId) > 0)
            linkField.text = ""
    }

    function showOptions() {
        var text = linkField.text.trim()
        if (text.length === 0) {
            page.pasteLink()
            text = linkField.text.trim()
        }
        if (text.length === 0) return
        page.optionsOpen = true
        analyzeController.analyze(text.split(/\s+/)[0])
    }

    // Put a link in the link box and read it, as Options does (the Sign-ins page's library shortcuts).
    function openLink(url) {
        linkField.text = url
        page.showOptions()
    }

    function addDropped(text) {
        if (queueController.addLinks(text, page.presetId) === 0)
            linkField.text = text
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spaceXl
        spacing: Theme.spaceLg

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm

            StyledTextField {
                id: linkField
                Layout.fillWidth: true
                placeholderText: "Paste a link to a video, playlist, or channel (several links: one per line)"
                toolTipText: "YouTube and every other site yt-dlp supports. Press Enter to download with the chosen preset."
                onAccepted: page.download()
                input.Keys.onEscapePressed: linkField.text = ""
            }
            AppButton {
                iconName: "paste"
                toolTipText: "Paste the copied link (Ctrl+V)"
                onClicked: page.pasteLink()
            }
            StyledComboBox {
                Layout.preferredWidth: 230
                model: prefsController.presets
                value: page.presetId
                accessibleName: "Preset"
                toolTipText: "How the Download button saves: the type, quality, and container"
                onActivated: prefsController.saveSettings({"downloads.preset": currentValue})
            }
            AppButton {
                text: "Options"
                iconName: "settings"
                enabled: toolsController.ready
                toolTipText: "Read the link first to choose quality, subtitles, and which videos to get (Ctrl+Shift+O)"
                onClicked: page.showOptions()
            }
            AppButton {
                kind: "primary"
                text: "Download"
                iconName: "download"
                enabled: toolsController.ready
                toolTipText: toolsController.ready ? "Download with the chosen preset (Enter)"
                    : "Get the download tools first"
                onClicked: page.download()
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
            visible: page.optionsOpen && (analyzeController.busy || analyzeController.hasResult)
            maxHeight: Math.max(240, page.height * 0.62)
            presetId: page.presetId
            onClosed: page.optionsOpen = false
        }

        // Above the list it acts on: finished downloads leave it, and the Library keeps their files.
        RowLayout {
            Layout.fillWidth: true
            visible: queueController.finishedCount > 0
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

            Keys.onSpacePressed: {
                var row = queueController.model.get(queueView.currentIndex)
                if (row.canPause) queueController.pause(row.jobId)
                else if (row.canResume || row.canRetry) queueController.resume(row.jobId)
            }
            Keys.onDeletePressed: {
                var row = queueController.model.get(queueView.currentIndex)
                if (row.jobId !== undefined) removeDialog.show(row.jobId, row.title)
            }
            Keys.onMenuPressed: {
                var row = queueController.model.get(queueView.currentIndex)
                if (row.jobId !== undefined) jobMenu.openFor(row.jobId)
            }

            delegate: JobItem {
                width: queueView.width
                current: ListView.isCurrentItem
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
                    + "Playlists and channels download whole; open Options to pick videos, quality, and subtitles."
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
        AppMenuItem { text: "Remove"; onTriggered: removeDialog.show(jobMenu.jobId, jobMenu.row.title) }
    }

    ExtractAudioDialog { id: extractDialog }

    AppDialog {
        id: removeDialog
        property int jobId: -1
        function show(jobId, title) {
            removeDialog.jobId = jobId
            removeName.text = title
            deleteFiles.checked = false
            removeDialog.open()
        }
        title: "Remove this download?"
        standardButtons: Dialog.Ok | Dialog.Cancel
        defaultButton: Dialog.Ok
        width: Math.min(page.width - 2 * Theme.spaceXl, 460)
        Component.onCompleted: removeDialog.standardButton(Dialog.Ok).text = "Remove"
        onAccepted: queueController.remove(removeDialog.jobId, deleteFiles.checked)

        ColumnLayout {
            width: parent.width
            spacing: Theme.spaceSm

            Text {
                id: removeName
                Layout.fillWidth: true
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
                text: "It leaves the download list. Its files stay in the folder unless you choose to delete them."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                color: Theme.text
                wrapMode: Text.WordWrap
            }
            CheckBox {
                id: deleteFiles
                Layout.leftMargin: -Theme.spaceSm
                text: "Also delete its files"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
            }
            Text {
                Layout.fillWidth: true
                text: "Saved files go to the Recycle Bin, where you can restore them; unfinished parts are deleted."
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
