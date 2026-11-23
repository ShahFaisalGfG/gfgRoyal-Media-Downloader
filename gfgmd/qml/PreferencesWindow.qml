// qmllint disable unqualified
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

import "components"

// Preferences, saved as they are changed, in sections listed down the side (as in gfgLock). Theme is
// previewed live and reconciled to the saved value when the window closes. showTools() opens it at
// the Tools section (from the first-run card).
AppWindow {
    id: prefsWin

    width: 880
    height: 680
    minimumWidth: 720
    minimumHeight: 520
    showMaximize: false
    visible: false
    title: appController.appName + " Preferences"

    function v(key) { prefsController.revision; return prefsController.value(key) }
    function save(key, value) { var update = {}; update[key] = value; prefsController.saveSettings(update) }
    function showTools() { nav.currentIndex = prefsWin.sections.findIndex(section => section.name === "Tools") }

    readonly property var sections: [
        { name: "General", icon: "settings" },
        { name: "Downloads", icon: "download" },
        { name: "Video", icon: "video" },
        { name: "Audio", icon: "audio" },
        { name: "Network and schedule", icon: "globe" },
        { name: "Subscriptions", icon: "bell" },
        { name: "Tools", icon: "repair" },
        { name: "Updates and logs", icon: "sync" }
    ]

    onClosing: appController.endPreview()
    onVisibleChanged: if (visible) toolsController.refresh()

    Connections {
        target: prefsController
        function onSaveFinished(ok, message) { if (message.length > 0) prefsToast.show(message) }
        function onOptimizeFinished(message) { optimizeResult.text = message }
    }
    // While this window is the one in use, the app's notices show here (the main window shows them otherwise).
    Connections {
        target: appController
        function onNotice(message) { if (prefsWin.active) prefsToast.show(message) }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // Section navigation, as in gfgLock's Preferences (Up/Down to move, Tab to the content).
            // The Control holds the focus, so the ring shows only when it came from the keyboard.
            Rectangle {
                Layout.fillHeight: true
                Layout.preferredWidth: 210
                color: Theme.surfaceAlt

                Control {
                    id: navBox
                    anchors.fill: parent
                    padding: Theme.spaceSm
                    focus: true
                    focusPolicy: Qt.TabFocus
                    Accessible.role: Accessible.PageTabList
                    Accessible.name: "Preference sections"
                    // The arrow keys are keyboard use too, so they bring up the ring.
                    Keys.onUpPressed: {
                        nav.decrementCurrentIndex()
                        navBox.focusReason = Qt.TabFocusReason
                        navBox.Accessible.announce(prefsWin.sections[nav.currentIndex].name)
                    }
                    Keys.onDownPressed: {
                        nav.incrementCurrentIndex()
                        navBox.focusReason = Qt.TabFocusReason
                        navBox.Accessible.announce(prefsWin.sections[nav.currentIndex].name)
                    }

                    contentItem: ListView {
                        id: nav
                        model: prefsWin.sections
                        spacing: 2
                        interactive: false

                        delegate: ItemDelegate {
                            id: navItem
                            required property var modelData
                            required property int index
                            width: ListView.view.width
                            height: 38
                            focusPolicy: Qt.NoFocus
                            highlighted: ListView.isCurrentItem
                            onClicked: {
                                nav.currentIndex = navItem.index
                                navBox.forceActiveFocus(Qt.MouseFocusReason)
                            }
                            Accessible.name: navItem.modelData.name
                            Accessible.role: Accessible.PageTab
                            Accessible.selectable: true
                            Accessible.selected: navItem.highlighted

                            contentItem: RowLayout {
                                spacing: Theme.spaceSm
                                Icon {
                                    name: navItem.modelData.icon
                                    size: Theme.iconMd
                                    color: navItem.highlighted ? Theme.accent : Theme.textMuted
                                }
                                Text {
                                    textFormat: Text.PlainText
                                    Layout.fillWidth: true
                                    text: navItem.modelData.name
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontBody
                                    font.weight: navItem.highlighted ? Font.DemiBold : Font.Normal
                                    color: Theme.text
                                    elide: Text.ElideRight
                                }
                            }
                            background: Rectangle {
                                radius: Theme.radius
                                color: navItem.highlighted ? Theme.accentSoft : (navItem.hovered ? Theme.surfaceHover : "transparent")
                                border.width: navBox.visualFocus && navItem.highlighted ? 2 : 0
                                border.color: Theme.focusRing
                            }
                        }
                    }
                }
            }

            Rectangle { Layout.fillHeight: true; Layout.preferredWidth: 1; color: Theme.border }

            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: nav.currentIndex

                // General
                PrefsPage {
                    Card {
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.spaceLg
                        Layout.rightMargin: Theme.spaceLg
                        title: "Appearance"
                        iconName: "settings"

                        SettingRow {
                            label: "Theme"
                            fillControl: true
                            StyledComboBox {
                                Layout.fillWidth: true
                                model: prefsController.options.theme
                                value: prefsController.theme
                                accessibleName: "Theme"
                                onActivated: {
                                    prefsController.saveSettings({ "theme": currentValue })
                                    appController.previewTheme(currentValue)
                                }
                            }
                        }
                    }
                    Card {
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.spaceLg
                        Layout.rightMargin: Theme.spaceLg
                        title: "Startup and notifications"
                        iconName: "power"

                        SettingRow {
                            label: "Start with Windows"
                            hint: "Starts in the tray so subscriptions keep being checked. Needs the installed version of the app."
                            AppSwitch { checked: prefsWin.v("startup.start_with_windows"); accessibleName: "Start with Windows"; onToggled: prefsWin.save("startup.start_with_windows", checked) }
                        }
                        SettingRow {
                            label: "Start in the tray"
                            AppSwitch { checked: prefsWin.v("tray.start_minimized"); accessibleName: "Start in the tray"; onToggled: prefsWin.save("tray.start_minimized", checked) }
                        }
                        SettingRow {
                            label: "Closing the window keeps the app in the tray"
                            AppSwitch { checked: prefsWin.v("tray.close_to_tray"); accessibleName: "Close to the tray"; onToggled: prefsWin.save("tray.close_to_tray", checked) }
                        }
                        SettingRow {
                            label: "Offer copied links"
                            hint: "When you copy a link the app can download, it offers to."
                            AppSwitch { checked: prefsWin.v("clipboard.watch"); accessibleName: "Offer copied links"; onToggled: prefsWin.save("clipboard.watch", checked) }
                        }
                        SettingRow {
                            label: "Notifications"
                            hint: "When downloads finish, fail, or need a sign-in, and when subscriptions find new uploads."
                            AppSwitch { checked: prefsWin.v("notifications.enabled"); accessibleName: "Notifications"; onToggled: prefsWin.save("notifications.enabled", checked) }
                        }
                        SettingRow {
                            label: "When downloads finish"
                            hint: "The starting choice each time the app opens; change it for now in the bar at the bottom."
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.whenDone; value: prefsWin.v("schedule.when_done"); accessibleName: "When downloads finish"; onActivated: prefsWin.save("schedule.when_done", currentValue) }
                        }
                    }
                }

                // Downloads
                PrefsPage {
                    Card {
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.spaceLg
                        Layout.rightMargin: Theme.spaceLg
                        title: "Downloads"
                        iconName: "download"

                        SettingRow {
                            label: "Video folder"
                            hint: prefsController.downloadFolder
                            RowLayout {
                                spacing: Theme.spaceSm
                                AppButton { text: "Change"; iconName: "folder"; toolTipText: "Choose where videos go"; onClicked: { folderDialog.key = "downloads.folder"; folderDialog.open() } }
                                AppButton { kind: "ghost"; iconName: "folderOpen"; toolTipText: "Open the folder"; onClicked: appController.openPath(prefsController.downloadFolder) }
                            }
                        }
                        SettingRow {
                            label: "Audio folder"
                            hint: prefsController.audioFolder
                            RowLayout {
                                spacing: Theme.spaceSm
                                AppButton { text: "Change"; iconName: "folder"; toolTipText: "Choose where music and other audio go"; onClicked: { folderDialog.key = "downloads.audio_folder"; folderDialog.open() } }
                                AppButton { kind: "ghost"; iconName: "folderOpen"; toolTipText: "Open the folder"; onClicked: appController.openPath(prefsController.audioFolder) }
                            }
                        }
                        SettingRow {
                            label: "Default preset"
                            fillControl: true
                            StyledComboBox {
                                Layout.fillWidth: true
                                model: prefsController.presets
                                value: prefsWin.v("downloads.preset")
                                accessibleName: "Default preset"
                                onActivated: prefsWin.save("downloads.preset", currentValue)
                            }
                        }
                        SettingRow {
                            label: "File names"
                            hint: "The quality is measured from the finished file, so a 1080p request that was only offered at 720p ends in (720p)."
                            fillControl: true
                            StyledComboBox {
                                Layout.fillWidth: true
                                model: prefsController.options.filename
                                value: prefsWin.v("downloads.filename_style")
                                accessibleName: "File names"
                                onActivated: prefsWin.save("downloads.filename_style", currentValue)
                            }
                        }
                        SettingRow {
                            label: "Downloads at once"
                            hint: "Automatic runs three, and at most two or three per site, which sites tolerate."
                            fillControl: true
                            StyledComboBox {
                                Layout.fillWidth: true
                                model: prefsController.options.concurrent
                                value: prefsWin.v("downloads.concurrent")
                                accessibleName: "Downloads at once"
                                onActivated: prefsWin.save("downloads.concurrent", currentValue)
                            }
                        }
                        SettingRow {
                            label: "Parts at once"
                            hint: "How many pieces of one video download at the same time. Automatic is 8; Optimize for this PC finds the fastest."
                            fillControl: true
                            StyledComboBox {
                                Layout.fillWidth: true
                                model: prefsController.options.fragments
                                value: prefsWin.v("downloads.fragments")
                                accessibleName: "Parts at once"
                                onActivated: prefsWin.save("downloads.fragments", currentValue)
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.spaceSm
                            StyledTextField {
                                id: optimizeLink
                                Layout.fillWidth: true
                                enabled: !prefsController.optimizing
                                placeholderText: "A video link to test with (a long one works best)"
                            }
                            AppButton {
                                text: prefsController.optimizing ? "Stop" : "Optimize for this PC"
                                iconName: prefsController.optimizing ? "stop" : "speed"
                                enabled: prefsController.optimizing || (optimizeLink.text.length > 0 && toolsController.ready)
                                toolTipText: "Download a few seconds of the video with 4, 8, and 16 parts at once and keep the fastest"
                                onClicked: prefsController.optimizing ? prefsController.cancelOptimize() : prefsController.startOptimize(optimizeLink.text)
                            }
                        }
                        ProgressBar {
                            Layout.fillWidth: true
                            visible: prefsController.optimizing
                            from: 0
                            to: 1
                            value: prefsController.optimizeProgress
                            Accessible.name: "Speed test progress"
                        }
                        Text {
                            id: optimizeResult
                            textFormat: Text.PlainText
                            Layout.fillWidth: true
                            visible: text.length > 0
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontCaption
                            color: Theme.textMuted
                            wrapMode: Text.WordWrap
                        }
                        SettingRow {
                            label: "Attempts"
                            hint: "After a temporary problem (a dropped connection) the app tries again, waiting longer each time, up to five minutes. 0 keeps trying until the download finishes or you stop it."
                            StyledSpinBox {
                                from: 0
                                to: 1000
                                value: prefsWin.v("downloads.max_attempts")
                                Accessible.name: "Attempts"
                                onValueModified: prefsWin.save("downloads.max_attempts", value)
                            }
                        }
                        SettingRow {
                            label: "Clear finished downloads when the app closes"
                            hint: "Their files stay in the Library. Failed and unfinished downloads stay in the list to be tried again or resumed."
                            AppSwitch {
                                checked: prefsWin.v("downloads.clear_finished_on_exit")
                                accessibleName: "Clear finished downloads when the app closes"
                                onToggled: prefsWin.save("downloads.clear_finished_on_exit", checked)
                            }
                        }
                        SettingRow {
                            label: "Keep the PC awake while downloading"
                            hint: "Windows doesn't sleep or hibernate on its own while downloads run or wait to try again. The screen can still turn off, and Sleep in the Start menu still works."
                            AppSwitch {
                                checked: prefsWin.v("downloads.keep_awake")
                                accessibleName: "Keep the PC awake while downloading"
                                onToggled: prefsWin.save("downloads.keep_awake", checked)
                            }
                        }
                    }
                }

                // Video
                PrefsPage {
                    Card {
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.spaceLg
                        Layout.rightMargin: Theme.spaceLg
                        title: "Video"
                        description: "The starting choices in Download options. The Download button uses the preset next to it, which sets its own quality and file type."
                        iconName: "video"

                        SettingRow {
                            label: "File type"
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.container; value: prefsWin.v("formats.container"); accessibleName: "File type"; onActivated: prefsWin.save("formats.container", currentValue) }
                        }
                        SettingRow {
                            label: "Compatibility"
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.codec; value: prefsWin.v("formats.codec_profile"); accessibleName: "Compatibility"; onActivated: prefsWin.save("formats.codec_profile", currentValue) }
                        }
                        SettingRow {
                            label: "Audio tracks"
                            hint: "Sites such as YouTube add dubbed languages to some videos. Extra languages need MP4 or MKV."
                            fillControl: true
                            StyledComboBox {
                                Layout.fillWidth: true
                                // "Every language" needs a video's own list, so it's offered in Download options only.
                                model: prefsController.options.audioTracks.slice(0, 2)
                                value: prefsWin.v("formats.audio_tracks") === "original" ? "original" : "languages"
                                accessibleName: "Audio tracks"
                                onActivated: prefsWin.save("formats.audio_tracks", currentValue)
                            }
                        }
                        SettingRow {
                            visible: prefsWin.v("formats.audio_tracks") !== "original"
                            label: "Extra audio languages"
                            hint: "Short language codes separated by commas, such as es (Spanish), pt-BR. A video without them keeps only its original language."
                            fillControl: true
                            StyledTextField {
                                Layout.fillWidth: true
                                placeholderText: "es, fr"
                                accessibleName: "Extra audio languages"
                                text: prefsWin.v("formats.audio_langs").join(", ")
                                onEditingFinished: prefsWin.save("formats.audio_langs",
                                    text.split(",").map(code => code.trim()).filter(code => code.length > 0))
                            }
                        }
                        SettingRow {
                            label: "Subtitles"
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.subtitles; value: prefsWin.v("formats.subtitles"); accessibleName: "Subtitles"; onActivated: prefsWin.save("formats.subtitles", currentValue) }
                        }
                        SettingRow {
                            visible: prefsWin.v("formats.subtitles") === "sidecar" || prefsWin.v("formats.subtitles") === "both"
                            label: "Subtitle files"
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.subtitleFormat; value: prefsWin.v("formats.subtitle_format"); accessibleName: "Subtitle file type"; onActivated: prefsWin.save("formats.subtitle_format", currentValue) }
                        }
                        SettingRow {
                            label: "Subtitle languages"
                            hint: "Short language codes separated by commas, without spaces: en.* is every kind of English."
                            fillControl: true
                            StyledTextField {
                                Layout.fillWidth: true
                                accessibleName: "Subtitle languages"
                                text: prefsWin.v("formats.subtitle_langs")
                                onEditingFinished: if (text.trim().length > 0) prefsWin.save("formats.subtitle_langs", text.trim())
                            }
                        }
                        SettingRow {
                            label: "Automatic captions"
                            AppSwitch { checked: prefsWin.v("formats.auto_subtitles"); accessibleName: "Automatic captions"; onToggled: prefsWin.save("formats.auto_subtitles", checked) }
                        }
                        SettingRow {
                            label: "Put the thumbnail in the file (the cover, for songs)"
                            AppSwitch { checked: prefsWin.v("formats.embed_thumbnail"); accessibleName: "Put the thumbnail in the file"; onToggled: prefsWin.save("formats.embed_thumbnail", checked) }
                        }
                        SettingRow {
                            label: "Put the title, uploader, and date in the file"
                            AppSwitch { checked: prefsWin.v("formats.embed_metadata"); accessibleName: "Put the details in the file"; onToggled: prefsWin.save("formats.embed_metadata", checked) }
                        }
                        SettingRow {
                            label: "Put chapter marks in the file"
                            AppSwitch { checked: prefsWin.v("formats.embed_chapters"); accessibleName: "Put chapter marks in the file"; onToggled: prefsWin.save("formats.embed_chapters", checked) }
                        }
                        SettingRow {
                            label: "SponsorBlock (YouTube)"
                            hint: "Cut or mark sponsor messages and reminders that SponsorBlock's community has tagged."
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.sponsorblock; value: prefsWin.v("formats.sponsorblock"); accessibleName: "SponsorBlock"; onActivated: prefsWin.save("formats.sponsorblock", currentValue) }
                        }
                        Flow {
                            Layout.fillWidth: true
                            visible: prefsWin.v("formats.sponsorblock") !== "off"
                            spacing: Theme.spaceSm
                            Repeater {
                                model: prefsController.options.sponsorCategories
                                delegate: AppCheckBox {
                                    required property var modelData
                                    text: modelData.label
                                    checked: prefsWin.v("formats.sponsorblock_categories").indexOf(modelData.code) >= 0
                                    onToggled: {
                                        var list = prefsWin.v("formats.sponsorblock_categories").filter(code => code !== modelData.code)
                                        if (checked) list.push(modelData.code)
                                        if (list.length > 0) {
                                            prefsWin.save("formats.sponsorblock_categories", list)
                                        } else {
                                            checked = true
                                            prefsToast.show("Keep at least one kind of segment ticked, or turn SponsorBlock off.")
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // Audio
                PrefsPage {
                    Card {
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.spaceLg
                        Layout.rightMargin: Theme.spaceLg
                        title: "Audio"
                        description: "The starting choices in Download options. The Download button uses the preset next to it, which sets its own format and quality."
                        iconName: "audio"

                        SettingRow {
                            label: "Format"
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.audio; value: prefsWin.v("formats.audio_format"); accessibleName: "Audio format"; onActivated: prefsWin.save("formats.audio_format", currentValue) }
                        }
                        SettingRow {
                            visible: prefsController.losslessAudio.indexOf(prefsWin.v("formats.audio_format")) < 0
                            label: "Quality"
                            hint: "Higher numbers sound better and make bigger files; above 256 the sound can't get better than the site's. "
                                + "M4A and Opus keep the site's sound as it is when they can."
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.audioQuality; value: prefsWin.v("formats.audio_quality"); accessibleName: "Audio quality"; onActivated: prefsWin.save("formats.audio_quality", currentValue) }
                        }
                        SettingRow {
                            label: "Cover"
                            hint: "The video's thumbnail becomes the song's cover (WAV songs get it as a picture next to the file)."
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.cover; value: prefsWin.v("formats.cover"); accessibleName: "Cover shape"; onActivated: prefsWin.save("formats.cover", currentValue) }
                        }
                        SettingRow {
                            label: "Lyrics"
                            hint: "Saves lyrics that the player shows line by line as the song plays, from the site's captions."
                            AppSwitch { checked: prefsWin.v("formats.lyrics"); accessibleName: "Save lyrics"; onToggled: prefsWin.save("formats.lyrics", checked) }
                        }
                        SettingRow {
                            visible: prefsWin.v("formats.lyrics")
                            label: "Look up lyrics online"
                            hint: "When a song has no captions, asks LRCLIB, a free online lyrics service, using the title, "
                                + "artist, album, and length. Only lyrics that match the song's length are used."
                            AppSwitch { checked: prefsWin.v("formats.lyrics_online"); accessibleName: "Look up lyrics online"; onToggled: prefsWin.save("formats.lyrics_online", checked) }
                        }
                    }
                }

                // Network and schedule
                PrefsPage {
                    Card {
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.spaceLg
                        Layout.rightMargin: Theme.spaceLg
                        title: "Network and schedule"
                        iconName: "globe"

                        SettingRow {
                            label: "Speed limit (kilobytes per second)"
                            hint: "The total for all downloads; 0 is no limit. Live recordings are never slowed."
                            StyledSpinBox {
                                from: 0
                                to: 1048576
                                stepSize: 128
                                value: prefsWin.v("network.limit_kib")
                                Accessible.name: "Speed limit in kilobytes per second"
                                onValueModified: prefsWin.save("network.limit_kib", value)
                            }
                        }
                        Text {
                            textFormat: Text.PlainText
                            Layout.fillWidth: true
                            text: "Limits by time of day (for example, slower during work hours):"
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontBody
                            color: Theme.text
                            wrapMode: Text.WordWrap
                        }
                        Repeater {
                            model: prefsWin.v("network.limit_windows")
                            delegate: RowLayout {
                                id: windowRow
                                required property var modelData
                                required property int index
                                Layout.fillWidth: true
                                Text {
                                    textFormat: Text.PlainText
                                    Layout.fillWidth: true
                                    text: windowRow.modelData.start + " to " + windowRow.modelData.end + ": " + windowRow.modelData.limit_kib + " kilobytes per second"
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontBody
                                    color: Theme.text
                                }
                                AppButton {
                                    kind: "ghost"
                                    compact: true
                                    iconName: "delete"
                                    toolTipText: "Remove this limit"
                                    onClicked: {
                                        var list = prefsWin.v("network.limit_windows").slice()
                                        list.splice(windowRow.index, 1)
                                        prefsWin.save("network.limit_windows", list)
                                    }
                                }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.spaceSm
                            StyledTextField { id: windowStart; Layout.preferredWidth: 80; placeholderText: "09:00"; accessibleName: "Limit from"; toolTipText: "From (24-hour time)" }
                            StyledTextField { id: windowEnd; Layout.preferredWidth: 80; placeholderText: "18:00"; accessibleName: "Limit until"; toolTipText: "Until (24-hour time); may pass midnight" }
                            StyledSpinBox { id: windowLimit; from: 16; to: 1048576; stepSize: 128; value: 512; Accessible.name: "Limit in kilobytes per second" }
                            Text {
                                textFormat: Text.PlainText
                                text: "KB/s"
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontCaption
                                color: Theme.textMuted
                                Accessible.ignored: true
                            }
                            AppButton {
                                text: "Add"
                                iconName: "add"
                                toolTipText: "Add this time-of-day limit"
                                onClicked: {
                                    var clock = /^([01]\d|2[0-3]):[0-5]\d$/
                                    if (!clock.test(windowStart.text) || !clock.test(windowEnd.text) || windowStart.text === windowEnd.text) {
                                        prefsToast.show("Type both times like 09:00 (24-hour), and make them different.")
                                        return
                                    }
                                    var list = prefsWin.v("network.limit_windows").slice()
                                    list.push({ "start": windowStart.text, "end": windowEnd.text, "limit_kib": windowLimit.value })
                                    prefsWin.save("network.limit_windows", list)
                                    windowStart.text = ""
                                    windowEnd.text = ""
                                }
                            }
                        }
                        SettingRow {
                            label: "Start downloads at"
                            hint: "Downloads wait until this time once (24-hour, such as 02:00). Leave empty to start right away."
                            fillControl: true
                            StyledTextField {
                                Layout.fillWidth: true
                                text: prefsWin.v("schedule.queue_start")
                                placeholderText: "Start right away"
                                accessibleName: "Start downloads at"
                                onEditingFinished: {
                                    var value = text.trim()
                                    if (value === "" || /^([01]\d|2[0-3]):[0-5]\d$/.test(value)) prefsWin.save("schedule.queue_start", value)
                                    else prefsToast.show("Type the time like 02:00 (24-hour).")
                                }
                            }
                        }
                        SettingRow {
                            label: "Proxy"
                            hint: "Only if your network needs one, such as http://proxy:8080. Downloads, lyrics, thumbnails, and the download tools go through it (a SOCKS proxy: downloads only). Leave empty to connect directly."
                            fillControl: true
                            StyledTextField {
                                Layout.fillWidth: true
                                text: prefsWin.v("network.proxy")
                                placeholderText: "No proxy"
                                accessibleName: "Proxy"
                                onEditingFinished: prefsWin.save("network.proxy", text.trim())
                            }
                        }
                        SettingRow {
                            label: "Connect over IPv4 only"
                            hint: "Try this if downloads are slow or fail to connect."
                            AppSwitch { checked: prefsWin.v("network.force_ipv4"); accessibleName: "Connect over IPv4 only"; onToggled: prefsWin.save("network.force_ipv4", checked) }
                        }
                    }
                }

                // Subscriptions
                PrefsPage {
                    Card {
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.spaceLg
                        Layout.rightMargin: Theme.spaceLg
                        title: "Subscriptions"
                        iconName: "bell"

                        SettingRow {
                            label: "How often new subscriptions are checked"
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.interval; value: prefsWin.v("subscriptions.interval_hours"); accessibleName: "How often new subscriptions are checked"; onActivated: prefsWin.save("subscriptions.interval_hours", currentValue) }
                        }
                        SettingRow {
                            label: "Download new uploads automatically"
                            AppSwitch { checked: prefsWin.v("subscriptions.auto_download"); accessibleName: "Download new uploads automatically"; onToggled: prefsWin.save("subscriptions.auto_download", checked) }
                        }
                    }
                }

                // Tools
                PrefsPage {
                    Card {
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.spaceLg
                        Layout.rightMargin: Theme.spaceLg
                        title: "Tools"
                        description: "The app downloads and converts with three free tools: yt-dlp, FFmpeg, and Deno. It keeps its own copies up to date, since sites change often."
                        iconName: "repair"

                        SettingRow {
                            label: "Where the tools come from"
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.toolSource; value: prefsWin.v("tools.source"); accessibleName: "Where the tools come from"; onActivated: prefsWin.save("tools.source", currentValue) }
                        }
                        SettingRow {
                            label: "Download tool updates"
                            fillControl: true
                            visible: prefsWin.v("tools.source") === "managed"
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.toolChannel; value: prefsWin.v("tools.channel"); accessibleName: "Download tool updates"; onActivated: prefsWin.save("tools.channel", currentValue) }
                        }
                        SettingRow {
                            label: "Update the tools automatically"
                            visible: prefsWin.v("tools.source") === "managed"
                            AppSwitch { checked: prefsWin.v("tools.auto_update"); accessibleName: "Update the tools automatically"; onToggled: prefsWin.save("tools.auto_update", checked) }
                        }
                        Repeater {
                            model: prefsWin.v("tools.source") === "custom" ? [["yt-dlp", "tools.ytdlp_path"], ["FFmpeg", "tools.ffmpeg_path"], ["Deno", "tools.deno_path"]] : []
                            delegate: SettingRow {
                                id: customRow
                                required property var modelData
                                label: customRow.modelData[0] + " program"
                                fillControl: true
                                StyledTextField {
                                    Layout.fillWidth: true
                                    text: prefsWin.v(customRow.modelData[1])
                                    placeholderText: "C:\\Tools\\" + customRow.modelData[0].toLowerCase() + ".exe"
                                    accessibleName: customRow.modelData[0] + " program file"
                                    onEditingFinished: prefsWin.save(customRow.modelData[1], text.trim())
                                }
                            }
                        }
                        Repeater {
                            model: toolsController.rows
                            delegate: RowLayout {
                                id: toolRow
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: Theme.spaceSm
                                Icon {
                                    name: toolRow.modelData.origin === "missing" ? "error" : "completed"
                                    size: Theme.iconSm
                                    color: toolRow.modelData.origin === "missing" ? Theme.danger : Theme.success
                                }
                                Text {
                                    textFormat: Text.PlainText
                                    Layout.fillWidth: true
                                    text: toolRow.modelData.label + "  " + (toolRow.modelData.version || "")
                                        + "  ·  " + ({"managed": "kept up to date by the app", "path": "installed on this PC", "custom": "where you chose", "missing": "not found"})[toolRow.modelData.origin]
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontBody
                                    color: Theme.text
                                    elide: Text.ElideRight
                                    ToolTip.text: toolRow.modelData.path
                                    ToolTip.visible: toolHover.hovered && toolRow.modelData.path.length > 0
                                    HoverHandler { id: toolHover }
                                }
                                AppButton {
                                    visible: toolRow.modelData.canRollBack
                                    kind: "ghost"
                                    text: "Previous version"
                                    toolTipText: "Go back to the version before the last update"
                                    onClicked: toolsController.rollBack(toolRow.modelData.name)
                                }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.spaceSm
                            visible: prefsWin.v("tools.source") === "managed"
                            AppButton { text: "Check for tool updates"; iconName: "sync"; enabled: !toolsController.busy; onClicked: toolsController.checkUpdates() }
                            AppButton { text: toolsController.ready ? "Update tools" : "Download tools"; iconName: "download"; enabled: !toolsController.busy && toolsController.canInstall; onClicked: toolsController.ready ? toolsController.updateAll() : toolsController.installMissing() }
                            AppButton { kind: "ghost"; iconName: "folderOpen"; toolTipText: "Open the tools folder"; onClicked: toolsController.openFolder() }
                        }
                        ProgressBar {
                            Layout.fillWidth: true
                            visible: toolsController.busy
                            from: 0
                            to: 1
                            value: Math.max(0, toolsController.progress)
                            indeterminate: toolsController.progress < 0
                            Accessible.name: "Tool download progress"
                        }
                        Text {
                            textFormat: Text.PlainText
                            Layout.fillWidth: true
                            visible: text.length > 0
                            text: toolsController.stage
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontCaption
                            color: Theme.textMuted
                            wrapMode: Text.WordWrap
                        }
                    }
                }

                // Updates and logs
                PrefsPage {
                    Card {
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.spaceLg
                        Layout.rightMargin: Theme.spaceLg
                        title: "Updates"
                        description: updateController.canSelfUpdate
                            ? "The app asks GitHub at most once a day whether a newer version is out. The request carries only the app's name and version. An update installs only after the app confirms it came from the publisher and wasn't changed."
                            : "This copy can't update itself because it isn't the installed version. The app still tells you when a new version is out, with a link to download it."
                        iconName: "sync"

                        SettingRow {
                            label: "Check for updates automatically"
                            hint: "Once a day while the app runs."
                            AppSwitch { checked: prefsController.autoCheckUpdates; accessibleName: "Check for updates automatically"; onToggled: prefsController.saveSettings({ "updates.auto_check": checked }) }
                        }
                        SettingRow {
                            visible: updateController.canSelfUpdate
                            label: "Install updates automatically"
                            hint: "Downloads in the background and installs when you quit. Waits while you're on mobile data or another limited connection."
                            AppSwitch { checked: prefsController.autoInstallUpdates; accessibleName: "Install updates automatically"; onToggled: prefsController.saveSettings({ "updates.auto_install": checked }) }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.spaceMd
                            AppButton {
                                text: "Check now"
                                iconName: "sync"
                                enabled: updateController.status !== "checking" && updateController.status !== "downloading"
                                toolTipText: "Ask GitHub whether a newer version is out"
                                onClicked: updateController.checkNow()
                            }
                            Text {
                                textFormat: Text.PlainText
                                Layout.fillWidth: true
                                visible: text !== ""
                                text: updateController.message
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontCaption
                                color: updateController.status === "error" ? Theme.danger : Theme.text
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                    Card {
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.spaceLg
                        Layout.rightMargin: Theme.spaceLg
                        title: "Logging"
                        description: "Off by default. Logs stay on this PC and never contain your sign-ins."
                        iconName: "info"

                        SettingRow {
                            label: "Save logs to a file"
                            AppSwitch { checked: prefsWin.v("advanced.enable_logs"); accessibleName: "Save logs to a file"; onToggled: prefsWin.save("advanced.enable_logs", checked) }
                        }
                        SettingRow {
                            label: "How much to save"
                            fillControl: true
                            enabled: prefsWin.v("advanced.enable_logs")
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.logLevel; value: prefsWin.v("advanced.log_level"); accessibleName: "Log detail"; onActivated: prefsWin.save("advanced.log_level", currentValue) }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.spaceSm
                            AppButton { text: "Open logs folder"; iconName: "openExternal"; onClicked: prefsController.openLogsFolder() }
                            AppButton { text: "Clear logs"; iconName: "clear"; onClicked: prefsController.clearLogs() }
                            Item { Layout.fillWidth: true }
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 60
            color: Theme.surface

            Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.spaceLg
                anchors.rightMargin: Theme.spaceLg
                spacing: Theme.spaceSm

                AppButton {
                    kind: "ghost"
                    text: "Reset to defaults"
                    toolTipText: "Every preference goes back to its default; saved presets, downloads, and sign-ins stay"
                    onClicked: resetDialog.open()
                }
                Item { Layout.fillWidth: true }
                AppButton {
                    kind: "primary"
                    text: "Close"
                    onClicked: prefsWin.close()
                }
            }
        }
    }

    AppDialog {
        id: resetDialog
        title: "Reset every preference?"
        standardButtons: Dialog.Ok | Dialog.Cancel
        defaultButton: Dialog.Cancel
        width: 420
        onAccepted: {
            prefsController.resetDefaults()
            appController.previewTheme(prefsController.theme)
            prefsToast.show("Every preference is back to its default.")
        }
        Component.onCompleted: resetDialog.standardButton(Dialog.Ok).text = "Reset"
        Text {
            textFormat: Text.PlainText
            width: parent.width
            text: "Folders, quality, speed limits, the proxy, and the start time go back to their defaults. Your presets, downloads, library, subscriptions, and sign-ins stay."
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.text
            wrapMode: Text.WordWrap
        }
    }

    FolderDialog {
        id: folderDialog
        // The setting the chosen folder is saved to: the video or the audio folder.
        property string key: "downloads.folder"
        title: folderDialog.key === "downloads.audio_folder" ? "Choose the audio folder" : "Choose the video folder"
        onAccepted: {
            var path = appController.localPath(selectedFolder.toString())
            if (path.length > 0) prefsWin.save(folderDialog.key, path)
        }
    }

    // A scrolling column of cards for one section. A Flickable whose bar draws over the cards' margin,
    // not a ScrollView: the content's width never depends on whether the bar shows (a ScrollView
    // narrows it for the bar, which can make rows re-wrap and the bar show or hide again).
    component PrefsPage: Flickable {
        id: section
        default property alias cards: column.data
        contentWidth: width
        contentHeight: column.implicitHeight + 2 * Theme.spaceLg
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        FocusScroll { flickable: section }

        ColumnLayout {
            id: column
            y: Theme.spaceLg
            width: section.width
            spacing: Theme.spaceLg
        }
    }

    Toast {
        id: prefsToast
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 76
    }
}
