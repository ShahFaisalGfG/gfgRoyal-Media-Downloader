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
                    Accessible.role: Accessible.List
                    Accessible.name: "Preference sections"
                    // The arrow keys are keyboard use too, so they bring up the ring.
                    Keys.onUpPressed: {
                        nav.decrementCurrentIndex()
                        navBox.focusReason = Qt.TabFocusReason
                    }
                    Keys.onDownPressed: {
                        nav.incrementCurrentIndex()
                        navBox.focusReason = Qt.TabFocusReason
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

                            contentItem: RowLayout {
                                spacing: Theme.spaceSm
                                Icon {
                                    name: navItem.modelData.icon
                                    size: Theme.iconMd
                                    color: navItem.highlighted ? Theme.accent : Theme.textMuted
                                }
                                Text {
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
                            hint: "Starts in the tray so subscriptions keep being checked. Works in the installed app."
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
                            hint: "Fragments of one video fetched in parallel. Automatic is 8; Optimize measures your connection."
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
                            Layout.fillWidth: true
                            visible: text.length > 0
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontCaption
                            color: Theme.textMuted
                            wrapMode: Text.WordWrap
                        }
                        SettingRow {
                            label: "Attempts"
                            hint: "Temporary failures (a dropped connection) are retried with growing waits up to five minutes. 0 keeps trying until the download finishes or you stop it."
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
                        description: "The starting choices for video presets and the Options panel."
                        iconName: "video"

                        SettingRow {
                            label: "Container"
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.container; value: prefsWin.v("formats.container"); accessibleName: "Container"; onActivated: prefsWin.save("formats.container", currentValue) }
                        }
                        SettingRow {
                            label: "Codecs"
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.codec; value: prefsWin.v("formats.codec_profile"); accessibleName: "Codec preference"; onActivated: prefsWin.save("formats.codec_profile", currentValue) }
                        }
                        SettingRow {
                            label: "Audio tracks"
                            hint: "Sites such as YouTube add dubbed languages to some videos. Extra tracks need MP4 or MKV."
                            fillControl: true
                            StyledComboBox {
                                Layout.fillWidth: true
                                // "Every language" needs a video's own list, so it's offered in the Options panel only.
                                model: prefsController.options.audioTracks.slice(0, 2)
                                value: prefsWin.v("formats.audio_tracks") === "original" ? "original" : "languages"
                                accessibleName: "Audio tracks"
                                onActivated: prefsWin.save("formats.audio_tracks", currentValue)
                            }
                        }
                        SettingRow {
                            visible: prefsWin.v("formats.audio_tracks") !== "original"
                            label: "Extra audio languages"
                            hint: "Language codes, comma separated, such as es, pt-BR. A video without them keeps its original track."
                            fillControl: true
                            StyledTextField {
                                Layout.fillWidth: true
                                placeholderText: "es, fr"
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
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.subtitleFormat; value: prefsWin.v("formats.subtitle_format"); accessibleName: "Subtitle file format"; onActivated: prefsWin.save("formats.subtitle_format", currentValue) }
                        }
                        SettingRow {
                            label: "Subtitle languages"
                            hint: "Comma separated; en.* is every English variant."
                            fillControl: true
                            StyledTextField {
                                Layout.fillWidth: true
                                text: prefsWin.v("formats.subtitle_langs")
                                onEditingFinished: if (text.trim().length > 0) prefsWin.save("formats.subtitle_langs", text.trim())
                            }
                        }
                        SettingRow {
                            label: "Automatic captions"
                            AppSwitch { checked: prefsWin.v("formats.auto_subtitles"); accessibleName: "Automatic captions"; onToggled: prefsWin.save("formats.auto_subtitles", checked) }
                        }
                        SettingRow {
                            label: "Embed the thumbnail (the cover, for audio)"
                            AppSwitch { checked: prefsWin.v("formats.embed_thumbnail"); accessibleName: "Embed the thumbnail"; onToggled: prefsWin.save("formats.embed_thumbnail", checked) }
                        }
                        SettingRow {
                            label: "Embed details (title, uploader, date)"
                            AppSwitch { checked: prefsWin.v("formats.embed_metadata"); accessibleName: "Embed details"; onToggled: prefsWin.save("formats.embed_metadata", checked) }
                        }
                        SettingRow {
                            label: "Embed chapters"
                            AppSwitch { checked: prefsWin.v("formats.embed_chapters"); accessibleName: "Embed chapters"; onToggled: prefsWin.save("formats.embed_chapters", checked) }
                        }
                        SettingRow {
                            label: "SponsorBlock (YouTube)"
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.sponsorblock; value: prefsWin.v("formats.sponsorblock"); accessibleName: "SponsorBlock"; onActivated: prefsWin.save("formats.sponsorblock", currentValue) }
                        }
                        Flow {
                            Layout.fillWidth: true
                            visible: prefsWin.v("formats.sponsorblock") !== "off"
                            spacing: Theme.spaceSm
                            Repeater {
                                model: prefsController.options.sponsorCategories
                                delegate: CheckBox {
                                    required property var modelData
                                    text: modelData.label
                                    font.family: Theme.fontFamily
                                    checked: prefsWin.v("formats.sponsorblock_categories").indexOf(modelData.code) >= 0
                                    onToggled: {
                                        var list = prefsWin.v("formats.sponsorblock_categories").filter(code => code !== modelData.code)
                                        if (checked) list.push(modelData.code)
                                        if (list.length > 0) prefsWin.save("formats.sponsorblock_categories", list)
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
                        description: "The starting choices for audio presets and the Options panel."
                        iconName: "audio"

                        SettingRow {
                            label: "Format"
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.audio; value: prefsWin.v("formats.audio_format"); accessibleName: "Audio format"; onActivated: prefsWin.save("formats.audio_format", currentValue) }
                        }
                        SettingRow {
                            visible: prefsController.losslessAudio.indexOf(prefsWin.v("formats.audio_format")) < 0
                            label: "Quality"
                            hint: "Sites stream audio at about 128-256 kbps; a higher bitrate keeps all of it but can't add detail. "
                                + "M4A and Opus keep the site's own stream unchanged when it already is one."
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.audioQuality; value: prefsWin.v("formats.audio_quality"); accessibleName: "Audio quality"; onActivated: prefsWin.save("formats.audio_quality", currentValue) }
                        }
                        SettingRow {
                            label: "Cover"
                            hint: "The video's thumbnail becomes the song's cover (beside the file for WAV)."
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.cover; value: prefsWin.v("formats.cover"); accessibleName: "Cover shape"; onActivated: prefsWin.save("formats.cover", currentValue) }
                        }
                        SettingRow {
                            label: "Lyrics"
                            hint: "Saves timed lyrics (a .lrc file the players show line by line) from the site's captions."
                            AppSwitch { checked: prefsWin.v("formats.lyrics"); accessibleName: "Save lyrics"; onToggled: prefsWin.save("formats.lyrics", checked) }
                        }
                        SettingRow {
                            visible: prefsWin.v("formats.lyrics")
                            label: "Look up lyrics online"
                            hint: "When a song has no captions, asks LRCLIB (lrclib.net, a free lyrics database) by title, "
                                + "artist, album, and length. Only lyrics timed to the same length are used."
                            AppSwitch { checked: prefsWin.v("formats.lyrics_online"); accessibleName: "Look up lyrics on LRCLIB"; onToggled: prefsWin.save("formats.lyrics_online", checked) }
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
                            label: "Speed limit (KB/s)"
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
                                    Layout.fillWidth: true
                                    text: windowRow.modelData.start + " to " + windowRow.modelData.end + ": " + windowRow.modelData.limit_kib + " KB/s"
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
                            StyledTextField { id: windowStart; Layout.preferredWidth: 80; placeholderText: "09:00"; toolTipText: "From (24-hour time)" }
                            StyledTextField { id: windowEnd; Layout.preferredWidth: 80; placeholderText: "18:00"; toolTipText: "Until (24-hour time); may pass midnight" }
                            StyledSpinBox { id: windowLimit; from: 16; to: 1048576; stepSize: 128; value: 512; Accessible.name: "Limit in kilobytes per second" }
                            AppButton {
                                text: "Add"
                                iconName: "add"
                                toolTipText: "Add this time-of-day limit"
                                onClicked: {
                                    var clock = /^([01]\d|2[0-3]):[0-5]\d$/
                                    if (!clock.test(windowStart.text) || !clock.test(windowEnd.text) || windowStart.text === windowEnd.text) {
                                        prefsToast.show("Times must look like 09:00 and differ.")
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
                            label: "Start the queue at"
                            hint: "Holds new downloads until this time once (24-hour, such as 02:00); empty starts at once."
                            fillControl: true
                            StyledTextField {
                                Layout.fillWidth: true
                                text: prefsWin.v("schedule.queue_start")
                                placeholderText: "Start at once"
                                onEditingFinished: {
                                    var value = text.trim()
                                    if (value === "" || /^([01]\d|2[0-3]):[0-5]\d$/.test(value)) prefsWin.save("schedule.queue_start", value)
                                    else prefsToast.show("The time must look like 02:00.")
                                }
                            }
                        }
                        SettingRow {
                            label: "Proxy"
                            hint: "http://, https://, or socks5://host:port; empty connects directly."
                            fillControl: true
                            StyledTextField {
                                Layout.fillWidth: true
                                text: prefsWin.v("network.proxy")
                                placeholderText: "No proxy"
                                onEditingFinished: prefsWin.save("network.proxy", text.trim())
                            }
                        }
                        SettingRow {
                            label: "Connect over IPv4 only"
                            hint: "Helps when IPv6 is slow or blocked."
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
                            label: "Check new subscriptions"
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.interval; value: prefsWin.v("subscriptions.interval_hours"); accessibleName: "Check interval"; onActivated: prefsWin.save("subscriptions.interval_hours", currentValue) }
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
                        description: "yt-dlp does the downloading, FFmpeg merges and converts, and Deno solves YouTube's player challenges. The app keeps its own copies current; sites change often, and a fresh yt-dlp keeps up."
                        iconName: "repair"

                        SettingRow {
                            label: "Source"
                            fillControl: true
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.toolSource; value: prefsWin.v("tools.source"); accessibleName: "Tool source"; onActivated: prefsWin.save("tools.source", currentValue) }
                        }
                        SettingRow {
                            label: "yt-dlp releases"
                            fillControl: true
                            visible: prefsWin.v("tools.source") === "managed"
                            StyledComboBox { Layout.fillWidth: true; model: prefsController.options.toolChannel; value: prefsWin.v("tools.channel"); accessibleName: "yt-dlp release channel"; onActivated: prefsWin.save("tools.channel", currentValue) }
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
                                    Layout.fillWidth: true
                                    text: toolRow.modelData.label + "  " + (toolRow.modelData.version || "")
                                        + "  ·  " + ({"managed": "the app's copy", "path": "on PATH", "custom": "your location", "missing": "not found"})[toolRow.modelData.origin]
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
                            AppButton { text: "Check for updates"; iconName: "sync"; enabled: !toolsController.busy; onClicked: toolsController.checkUpdates() }
                            AppButton { text: toolsController.ready ? "Update all" : "Download tools"; iconName: "download"; enabled: !toolsController.busy && toolsController.canInstall; onClicked: toolsController.ready ? toolsController.updateAll() : toolsController.installMissing() }
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
                            ? "The app asks GitHub at most once a day whether a newer version is out. The request carries only the app's name and version. An update installs only after its publisher signature and checksums match."
                            : "This copy runs from an unpacked folder, so it can't replace itself. The app still tells you when a new version is out, with a link to download it."
                        iconName: "sync"

                        SettingRow {
                            label: "Check for updates automatically"
                            hint: "Once a day while the app runs."
                            AppSwitch { checked: prefsController.autoCheckUpdates; accessibleName: "Check for updates automatically"; onToggled: prefsController.saveSettings({ "updates.auto_check": checked }) }
                        }
                        SettingRow {
                            visible: updateController.canSelfUpdate
                            label: "Install updates automatically"
                            hint: "Downloads in the background and installs when you quit. Not on a metered connection."
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
                        description: "Off by default. Logs stay on this PC and never contain sign-in cookies."
                        iconName: "info"

                        SettingRow {
                            label: "Save logs to a file"
                            AppSwitch { checked: prefsWin.v("advanced.enable_logs"); accessibleName: "Save logs to a file"; onToggled: prefsWin.save("advanced.enable_logs", checked) }
                        }
                        SettingRow {
                            label: "Detail"
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
                    onClicked: {
                        prefsController.resetDefaults()
                        appController.previewTheme(prefsController.theme)
                    }
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
