// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A link's details and every choice for downloading it: type, quality, container, codecs, audio
// tracks, subtitles, audio format and bitrate, cover, lyrics, embedding, SponsorBlock, live
// recording, and (for playlists and channels) which videos.
Rectangle {
    id: panel

    // The preset chosen next to the link box; the panel starts from its values.
    property string presetId: ""
    // The tallest the panel grows; the rest scrolls.
    property real maxHeight: 520
    // Dubbed audio languages ticked for this video (codes).
    property var pickedLangs: []
    readonly property bool audio: kindBox.currentValue === "audio"
    readonly property bool lossless: prefsController.losslessAudio.indexOf(audioBox.currentValue) >= 0
    // Lyrics captions in the song's own language first, then the subtitle languages.
    readonly property string lyricLangs: (analyzeController.language ? analyzeController.language + ".*," : "")
        + (langs.text.trim() || "en.*")

    signal closed()
    // The link was added to the queue with these choices.
    signal queued()

    function _pref(key) { return prefsController.value(key) }

    // Fill the controls from the preset over the format preferences.
    function reset() {
        var preset = prefsController.preset(panel.presetId)
        kindBox.value = preset.kind || "video"
        heightBox.value = preset.max_height !== undefined ? preset.max_height : 0
        containerBox.value = preset.container || panel._pref("formats.container")
        codecBox.value = preset.codec_profile || panel._pref("formats.codec_profile")
        audioBox.value = preset.audio_format || panel._pref("formats.audio_format")
        qualityBox.value = preset.audio_quality || panel._pref("formats.audio_quality")
        coverBox.value = preset.cover || panel._pref("formats.cover")
        lyricsSwitch.checked = preset.lyrics !== undefined ? preset.lyrics : panel._pref("formats.lyrics")
        tracksBox.value = preset.audio_tracks || panel._pref("formats.audio_tracks")
        trackLangs.text = (preset.audio_langs || panel._pref("formats.audio_langs")).join(", ")
        panel.pickedLangs = preset.audio_langs || panel._pref("formats.audio_langs")
        subtitlesBox.value = preset.subtitles || panel._pref("formats.subtitles")
        subFormatBox.value = preset.subtitle_format || panel._pref("formats.subtitle_format")
        langs.text = panel._pref("formats.subtitle_langs")
        autoSubs.checked = panel._pref("formats.auto_subtitles")
        embedThumb.checked = panel._pref("formats.embed_thumbnail")
        embedMeta.checked = panel._pref("formats.embed_metadata")
        embedChapters.checked = panel._pref("formats.embed_chapters")
        sponsorBox.value = preset.sponsorblock || panel._pref("formats.sponsorblock")
        fromStart.checked = true
    }

    // The dubbed languages to keep: every one, the ticked ones, or (playlists) the typed codes.
    function extraLangs() {
        var mode = tracksBox.currentValue
        if (mode === "original") return []
        var tracks = analyzeController.audioTracks
        if (tracks.length > 1) {
            var others = tracks.filter(track => !track.original).map(track => track.code)
            return mode === "all" ? others : panel.pickedLangs.filter(code => others.indexOf(code) >= 0)
        }
        return trackLangs.text.split(",").map(code => code.trim()).filter(code => code.length > 0)
    }

    function options() {
        var audio = panel.audio
        var extra = audio ? [] : panel.extraLangs()
        return {
            "kind": kindBox.currentValue,
            "max_height": heightBox.currentValue,
            // Several audio tracks need MP4 or MKV; a WebM choice becomes MKV.
            "container": extra.length > 0 && containerBox.currentValue === "webm" ? "mkv" : containerBox.currentValue,
            "codec_profile": codecBox.currentValue,
            "audio_tracks": extra.length > 0 ? tracksBox.currentValue : "original",
            "audio_langs": extra,
            "audio_format": audioBox.currentValue,
            "audio_quality": qualityBox.currentValue,
            "cover": coverBox.currentValue,
            "lyrics": lyricsSwitch.checked,
            "subtitles": audio ? "none" : subtitlesBox.currentValue,
            "subtitle_format": subFormatBox.currentValue,
            "subtitle_langs": audio ? panel.lyricLangs : (langs.text.trim() || "en.*"),
            "auto_subtitles": autoSubs.checked,
            "embed_thumbnail": embedThumb.checked,
            "embed_metadata": embedMeta.checked,
            "embed_chapters": embedChapters.checked,
            "sponsorblock": analyzeController.siteKey === "youtube" ? sponsorBox.currentValue : "off",
            "live_from_start": analyzeController.liveStatus === "is_live" && fromStart.checked,
        }
    }

    implicitHeight: Math.min(column.implicitHeight + 2 * Theme.spaceLg
                             + (actions.visible ? actions.implicitHeight + Theme.spaceMd : 0), panel.maxHeight)
    radius: Theme.radiusLarge
    color: Theme.surface
    border.width: 1
    border.color: Theme.border

    onVisibleChanged: if (visible) panel.reset()

    // The keys the buttons' tooltips name: Esc closes the options, Ctrl+Enter adds the download. An
    // open list or dialog takes Esc first, so Esc there closes only that.
    Shortcut {
        sequence: "Escape"
        enabled: panel.visible && !presetDialog.opened
        onActivated: closeButton.clicked()
    }
    Shortcut {
        sequences: ["Ctrl+Return", "Ctrl+Enter"]
        enabled: panel.visible && addButton.enabled && !presetDialog.opened
        onActivated: addButton.clicked()
    }
    FocusScroll { flickable: scroller }

    // The panel scrolls inside maxHeight, so a long playlist never squeezes the queue below it; the
    // action row stays pinned below the scrolling part. A Flickable rather than a ScrollView: the
    // content's width must not depend on whether the scroll bar shows. A ScrollView narrows its content
    // for the bar, so rows that wrap taller or shorter can make the bar show or hide again. The bar
    // draws over a gutter kept free on the right instead.
    Flickable {
        id: scroller
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: actions.visible ? actions.top : parent.bottom
        anchors.margins: Theme.spaceLg
        anchors.rightMargin: Theme.spaceSm
        anchors.bottomMargin: actions.visible ? Theme.spaceMd : Theme.spaceLg
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: column
            // Always the same width, whether or not the bar shows: a fixed gutter holds the bar.
            width: scroller.width - (Theme.spaceLg - Theme.spaceSm)
            spacing: Theme.spaceMd

            // Details
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spaceMd

                Thumb {
                    Layout.preferredWidth: 160
                    Layout.preferredHeight: 90
                    source: analyzeController.thumbnail
                    // Follows the Type choice: Audio only previews the song's square cover.
                    kind: panel.audio ? "audio"
                        : analyzeController.liveStatus === "is_live" || analyzeController.liveStatus === "is_upcoming"
                        ? "live" : "video"
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spaceXs
                    Text {
                        textFormat: Text.PlainText
                        Layout.fillWidth: true
                        text: analyzeController.busy ? "Reading the link..." : analyzeController.title
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSubtitle
                        font.weight: Font.DemiBold
                        color: Theme.text
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                    Text {
                        textFormat: Text.PlainText
                        Layout.fillWidth: true
                        text: analyzeController.busy ? analyzeController.status
                            : [analyzeController.uploader, analyzeController.siteLabel, analyzeController.details]
                                .filter(part => part.length > 0).join("  ·  ")
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontCaption
                        color: Theme.textMuted
                        elide: Text.ElideRight
                    }
                    RowLayout {
                        spacing: Theme.spaceSm
                        StatusBadge {
                            visible: analyzeController.liveStatus === "is_live"
                            text: "Live now"
                            iconName: "live"
                            tone: "danger"
                        }
                        StatusBadge {
                            visible: analyzeController.liveStatus === "is_upcoming"
                            text: analyzeController.startsText ? "Starts " + analyzeController.startsText : "Scheduled"
                            iconName: "clock"
                            tone: "warning"
                        }
                    }
                    BusyIndicator {
                        visible: analyzeController.busy
                        running: visible
                        implicitWidth: 28
                        implicitHeight: 28
                    }
                }
                AppButton {
                    id: closeButton
                    Layout.alignment: Qt.AlignTop
                    kind: "ghost"
                    compact: true
                    iconName: "close"
                    toolTipText: "Close the options (Esc)"
                    onClicked: {
                        analyzeController.clear()
                        panel.closed()
                    }
                }
            }

            // Choices
            GridLayout {
                Layout.fillWidth: true
                visible: analyzeController.hasResult
                columns: width > 760 ? 2 : 1
                // Equal columns: sized by their content, the rows (which stack their labels when narrow)
                // and the column widths would keep resizing each other.
                uniformCellWidths: true
                columnSpacing: Theme.spaceXl
                rowSpacing: Theme.spaceSm

                FormRow {
                    Layout.fillWidth: true
                    label: "Type"
                    labelWidth: 110
                    StyledComboBox {
                        id: kindBox
                        Layout.fillWidth: true
                        model: prefsController.options.kind
                        accessibleName: "Type"
                        toolTipText: "Download the video, or only its audio"
                        onActivated: analyzeController.refreshArchived(panel.options())
                    }
                }
                FormRow {
                    Layout.fillWidth: true
                    label: kindBox.currentValue === "audio" ? "Audio format" : "Quality"
                    labelWidth: 110
                    StyledComboBox {
                        id: heightBox
                        Layout.fillWidth: true
                        visible: kindBox.currentValue !== "audio"
                        model: analyzeController.heightOptions
                        accessibleName: "Highest quality"
                        toolTipText: "The best quality up to this one; measured on the shorter side, so it suits portrait videos too"
                        onActivated: analyzeController.refreshArchived(panel.options())
                    }
                    StyledComboBox {
                        id: audioBox
                        Layout.fillWidth: true
                        visible: kindBox.currentValue === "audio"
                        model: prefsController.options.audio
                        accessibleName: "Audio format"
                        toolTipText: "MP3 plays everywhere; FLAC and WAV keep full quality (bigger files); Original keeps the site's sound as it is"
                        onActivated: analyzeController.refreshArchived(panel.options())
                    }
                }
                FormRow {
                    Layout.fillWidth: true
                    visible: panel.audio && !panel.lossless
                    label: "Audio quality"
                    labelWidth: 110
                    StyledComboBox {
                        id: qualityBox
                        Layout.fillWidth: true
                        model: prefsController.options.audioQuality
                        accessibleName: "Audio quality"
                        toolTipText: "Higher numbers sound better and make bigger files; above 256 the sound can't get better than the site's"
                        onActivated: analyzeController.refreshArchived(panel.options())
                    }
                }
                FormRow {
                    Layout.fillWidth: true
                    visible: panel.audio && embedThumb.checked
                    label: "Cover"
                    labelWidth: 110
                    StyledComboBox {
                        id: coverBox
                        Layout.fillWidth: true
                        model: prefsController.options.cover
                        accessibleName: "Cover shape"
                        toolTipText: "The video's thumbnail becomes the song's cover; square crops it like an album cover"
                    }
                }
                FormRow {
                    Layout.fillWidth: true
                    visible: panel.audio
                    label: "Lyrics"
                    labelWidth: 110
                    AppSwitch {
                        id: lyricsSwitch
                        accessibleName: "Save lyrics"
                        toolTipText: "Save lyrics that follow along with the song, from the site's captions"
                            + (prefsController.value("formats.lyrics_online") ? " or a free online lyrics service" : "")
                            + "; the audio player shows them line by line"
                    }
                }
                FormRow {
                    Layout.fillWidth: true
                    visible: kindBox.currentValue !== "audio"
                    label: "File type"
                    labelWidth: 110
                    StyledComboBox {
                        id: containerBox
                        Layout.fillWidth: true
                        model: prefsController.options.container
                        accessibleName: "File type"
                        toolTipText: "MP4 plays everywhere; MKV keeps the best picture, subtitles, and chapters"
                    }
                }
                FormRow {
                    Layout.fillWidth: true
                    visible: kindBox.currentValue !== "audio"
                    label: "Compatibility"
                    labelWidth: 110
                    StyledComboBox {
                        id: codecBox
                        Layout.fillWidth: true
                        model: prefsController.options.codec
                        accessibleName: "Compatibility"
                        toolTipText: "Plays everywhere picks what every player handles; Best quality may not play on older devices"
                    }
                }
                FormRow {
                    Layout.fillWidth: true
                    visible: !panel.audio && (analyzeController.audioTracks.length > 1 || analyzeController.isPlaylist)
                    label: "Audio tracks"
                    labelWidth: 110
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.spaceXs
                        StyledComboBox {
                            id: tracksBox
                            Layout.fillWidth: true
                            // "Every language" needs this video's own list, so playlists get the first two.
                            model: analyzeController.audioTracks.length > 1 ? prefsController.options.audioTracks
                                : prefsController.options.audioTracks.slice(0, 2)
                            accessibleName: "Audio tracks"
                            toolTipText: "Keep only the original language, or dubbed languages too (as extra tracks in one file)"
                        }
                        Flow {
                            Layout.fillWidth: true
                            visible: tracksBox.currentValue === "languages" && analyzeController.audioTracks.length > 1
                            spacing: Theme.spaceSm
                            Repeater {
                                model: analyzeController.audioTracks.filter(track => !track.original)
                                delegate: CheckBox {
                                    required property var modelData
                                    text: modelData.label
                                    font.family: Theme.fontFamily
                                    checked: panel.pickedLangs.indexOf(modelData.code) >= 0
                                    onToggled: {
                                        var picked = panel.pickedLangs.filter(code => code !== modelData.code)
                                        if (checked) picked.push(modelData.code)
                                        panel.pickedLangs = picked
                                    }
                                }
                            }
                        }
                        StyledTextField {
                            id: trackLangs
                            Layout.fillWidth: true
                            visible: tracksBox.currentValue === "languages" && analyzeController.audioTracks.length <= 1
                            placeholderText: "es, fr"
                            accessibleName: "Extra audio languages"
                            toolTipText: "Short language codes separated by commas, such as es for Spanish; a video without them keeps its original language"
                        }
                        Text {
                            textFormat: Text.PlainText
                            Layout.fillWidth: true
                            visible: tracksBox.currentValue !== "original" && containerBox.currentValue === "webm"
                            text: "Videos with more than one language are saved as MKV."
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontCaption
                            color: Theme.textMuted
                            wrapMode: Text.WordWrap
                        }
                    }
                }
                FormRow {
                    Layout.fillWidth: true
                    visible: kindBox.currentValue !== "audio"
                    label: "Subtitles"
                    labelWidth: 110
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.spaceSm
                        StyledComboBox {
                            id: subtitlesBox
                            Layout.fillWidth: true
                            model: prefsController.options.subtitles
                            accessibleName: "Subtitles"
                            toolTipText: "Embed subtitles in the video, save them as files beside it, or both"
                        }
                        StyledComboBox {
                            id: subFormatBox
                            Layout.preferredWidth: 130
                            visible: subtitlesBox.currentValue === "sidecar" || subtitlesBox.currentValue === "both"
                            model: prefsController.options.subtitleFormat
                            accessibleName: "Subtitle file type"
                            toolTipText: "SRT works in most players; VTT keeps more of the text styling"
                        }
                        StyledTextField {
                            id: langs
                            Layout.preferredWidth: 110
                            visible: subtitlesBox.currentValue !== "none"
                            placeholderText: "en.*"
                            accessibleName: "Subtitle languages"
                            toolTipText: "Short language codes separated by commas, without spaces: en.* is every kind of English"
                                + (analyzeController.subtitleLangs.length
                                   ? ". This video has: " + analyzeController.subtitleLangs.slice(0, 12)
                                       .map(code => playerController.languageName(code) + " (" + code + ")").join(", ") : "")
                        }
                    }
                }
                FormRow {
                    Layout.fillWidth: true
                    visible: !panel.audio && subtitlesBox.currentValue !== "none" && analyzeController.subtitleLangs.length > 0
                    label: "This video has"
                    labelWidth: 110
                    // This video's subtitle languages: a click adds or removes one from the list above.
                    Flow {
                        Layout.fillWidth: true
                        spacing: Theme.spaceXs
                        Repeater {
                            model: analyzeController.subtitleLangs.slice(0, 16)
                            delegate: AppButton {
                                required property string modelData
                                readonly property var codes: langs.text.split(",").map(code => code.trim())
                                compact: true
                                kind: codes.indexOf(modelData) >= 0 ? "primary" : "ghost"
                                readonly property string name: playerController.languageName(modelData)
                                text: name
                                toolTipText: codes.indexOf(modelData) >= 0 ? "Leave out " + name : "Add " + name
                                onClicked: {
                                    var list = codes.filter(code => code.length > 0 && code !== modelData)
                                    if (codes.indexOf(modelData) < 0) list.push(modelData)
                                    langs.text = list.join(",")
                                }
                            }
                        }
                    }
                }
                FormRow {
                    Layout.fillWidth: true
                    visible: kindBox.currentValue !== "audio" && subtitlesBox.currentValue !== "none"
                    label: "Automatic captions"
                    labelWidth: 110
                    AppSwitch {
                        id: autoSubs
                        accessibleName: "Include automatic captions"
                        toolTipText: "Also take the site's machine-made captions when no written subtitles exist"
                    }
                }
                FormRow {
                    Layout.fillWidth: true
                    label: "In the file"
                    labelWidth: 110
                    RowLayout {
                        spacing: Theme.spaceLg
                        CheckBox { id: embedThumb; text: panel.audio ? "Cover" : "Thumbnail"; font.family: Theme.fontFamily; ToolTip.text: "Show the thumbnail as the file's cover"; ToolTip.visible: hovered }
                        CheckBox { id: embedMeta; text: "Details"; font.family: Theme.fontFamily; ToolTip.text: "Title, uploader, date, and description inside the file"; ToolTip.visible: hovered }
                        CheckBox { id: embedChapters; text: "Chapters"; font.family: Theme.fontFamily; ToolTip.text: "Chapter marks players can jump to"; ToolTip.visible: hovered }
                    }
                }
                FormRow {
                    Layout.fillWidth: true
                    visible: analyzeController.siteKey === "youtube"
                    label: "SponsorBlock"
                    labelWidth: 110
                    StyledComboBox {
                        id: sponsorBox
                        Layout.fillWidth: true
                        model: prefsController.options.sponsorblock
                        accessibleName: "SponsorBlock"
                        toolTipText: "Mark or cut sponsor messages and reminders that SponsorBlock's community has tagged"
                    }
                }
                FormRow {
                    Layout.fillWidth: true
                    visible: analyzeController.liveStatus === "is_live"
                    label: "Live stream"
                    labelWidth: 110
                    AppSwitch {
                        id: fromStart
                        accessibleName: "Record from the start"
                        toolTipText: "Record from the beginning of the stream (where the site allows) instead of from now"
                    }
                }
            }

            Text {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                visible: analyzeController.liveStatus === "is_upcoming"
                text: "The stream hasn't started yet. It waits in Downloads and starts recording when the stream begins."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.textMuted
                wrapMode: Text.WordWrap
            }

            EntryList {
                Layout.fillWidth: true
                visible: analyzeController.isPlaylist && analyzeController.selectable
                model: analyzeController.entries
            }

            Text {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                visible: analyzeController.isPlaylist && !analyzeController.selectable
                // A channel's tabs, or a signed-in account's own playlists: lists of lists.
                text: "Each playlist here downloads whole, into a folder of its own."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.textMuted
                wrapMode: Text.WordWrap
            }
        }
    }

    RowLayout {
        id: actions
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: Theme.spaceLg
        visible: analyzeController.hasResult
        spacing: Theme.spaceSm

        AppButton {
            kind: "ghost"
            text: "Save as preset"
            iconName: "add"
            toolTipText: "Keep these choices in the list next to the Download button"
            onClicked: presetDialog.open()
        }
        Item { Layout.fillWidth: true }
        AppButton {
            id: addButton
            kind: "primary"
            text: analyzeController.liveStatus === "is_upcoming" ? "Wait and record"
                : analyzeController.liveStatus === "is_live" ? "Record" : "Add to queue"
            iconName: analyzeController.liveStatus ? "live" : "download"
            toolTipText: "Add this download with the choices above (Ctrl+Enter)"
            onClicked: if (analyzeController.addToQueue(panel.options())) {
                panel.queued()
                panel.closed()
            }
        }
    }

    AppDialog {
        id: presetDialog
        title: "Save as preset"
        standardButtons: Dialog.Save | Dialog.Cancel
        defaultButton: Dialog.Save
        width: 380
        onOpened: presetName.selectInput()
        onAccepted: {
            var values = panel.options()
            values.label = presetName.text
            if (prefsController.savePreset(values)) presetName.text = ""
        }
        StyledTextField {
            id: presetName
            width: parent.width
            label: "Name"
            placeholderText: "Lectures, 720p with English subtitles"
        }
    }
}
