// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Download options: a link's details and the choices for downloading it, starting from the Video
// or Audio defaults in Preferences. The everyday choices come first (quality and file type, or the
// audio format and quality; subtitles; dubbed tracks; lyrics); compatibility, where subtitles go,
// what goes inside the file, the cover's shape, and SponsorBlock fold away under Advanced. A video
// inside a playlist chooses between itself and the playlist; a playlist or channel lists its videos
// as they are read. Several links share one set of choices.
Rectangle {
    id: panel

    // "video" or "audio": the Video | Audio switch beside the link box.
    property string kind: "video"
    // The tallest the panel grows; the rest scrolls.
    property real maxHeight: 520
    // Dubbed audio languages ticked for this video (codes).
    property var pickedLangs: []
    // The subtitle languages ticked (a video's own codes, or plain language codes for a list).
    property var subtitleCodes: []
    property bool _subtitlesEdited: false
    // Advanced stays open or closed for the session.
    property bool advancedOpen: false

    readonly property bool audio: panel.kind === "audio"
    readonly property bool lossless: prefsController.losslessAudio.indexOf(audioBox.currentValue) >= 0
    // A list's videos (or several links) differ, so their choices can't name one video's tracks.
    readonly property bool many: analyzeController.isPlaylist || analyzeController.linkCount > 0
    // This video's own subtitles; a list gets the common languages to pick from.
    readonly property var subtitleModel: panel.many ? prefsController.options.subtitleLanguages
                                                    : analyzeController.subtitleTracks
    readonly property bool hasSubtitles: panel.subtitleCodes.length > 0
    // Lyrics captions in the song's own language first, then the subtitle languages from Preferences.
    readonly property string lyricLangs: (analyzeController.language ? analyzeController.language + ".*," : "")
        + panel._pref("formats.subtitle_langs")

    signal closed()
    // The link was added to the queue with these choices.
    signal queued()

    function _pref(key) { return prefsController.value(key) }

    // Fill the controls from the Video and Audio defaults in Preferences.
    function reset() {
        heightBox.value = panel._pref("formats.max_height")
        containerBox.value = panel._pref("formats.container")
        codecBox.value = panel._pref("formats.codec_profile")
        audioBox.value = panel._pref("formats.audio_format")
        qualityBox.value = panel._pref("formats.audio_quality")
        coverBox.value = panel._pref("formats.cover")
        lyricsSwitch.checked = panel._pref("formats.lyrics")
        tracksBox.value = panel._pref("formats.audio_tracks")
        trackLangs.text = panel._pref("formats.audio_langs").join(", ")
        panel.pickedLangs = panel._pref("formats.audio_langs")
        placementBox.value = panel._pref("formats.subtitle_placement")
        subFormatBox.value = panel._pref("formats.subtitle_format")
        autoSubs.checked = panel._pref("formats.auto_subtitles")
        sponsorBox.value = panel._pref("formats.sponsorblock")
        fromStart.checked = panel._pref("downloads.live_from_start")
        panel._resetEmbeds()
        panel._subtitlesEdited = false
        panel._resetSubtitles()
    }
    // Video and audio each have their own "Save in the file" defaults.
    function _resetEmbeds() {
        embedThumb.checked = panel._pref(panel.audio ? "formats.audio_embed_cover" : "formats.embed_thumbnail")
        embedMeta.checked = panel._pref(panel.audio ? "formats.audio_embed_metadata" : "formats.embed_metadata")
        embedChapters.checked = panel._pref(panel.audio ? "formats.audio_embed_chapters" : "formats.embed_chapters")
    }
    // The languages Preferences names, ticked in this video's list (its machine-made captions only
    // when Preferences takes automatic captions), or in the common list.
    function _resetSubtitles() {
        if (panel._pref("formats.subtitles") === "none") {
            panel.subtitleCodes = []
            return
        }
        var patterns = String(panel._pref("formats.subtitle_langs")).split(",").filter(part => part.length > 0)
        var automatic = panel._pref("formats.auto_subtitles")
        panel.subtitleCodes = panel.subtitleModel
            .filter(item => (item.kind === "creator" || item.kind === "language" || automatic)
                    && patterns.some(pattern => panel._matches(pattern, item.code)))
            .map(item => item.code)
    }
    // yt-dlp's language patterns are regular expressions ("en.*").
    function _matches(pattern, code) {
        try {
            return new RegExp("^(?:" + pattern + ")$").test(code)
        } catch (error) {
            return pattern === code
        }
    }

    // The dubbed languages to keep: every one, the ticked ones, or (lists) the typed codes.
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
        var codes = audio ? [] : panel.subtitleCodes
        var tracks = analyzeController.subtitleTracks
        // A video's own list names exact tracks (machine-made ones need automatic captions); a list's
        // languages are patterns each video matches with what it has.
        var languages = panel.many ? codes.map(code => code + ".*") : codes
        var automatic = panel.many ? autoSubs.checked
            : codes.some(code => tracks.some(track => track.code === code && track.kind !== "creator"))
        return {
            "kind": panel.kind,
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
            "subtitles": codes.length > 0 ? placementBox.currentValue : "none",
            "subtitle_format": subFormatBox.currentValue,
            "subtitle_langs": audio ? panel.lyricLangs
                : languages.length > 0 ? languages.join(",") : panel._pref("formats.subtitle_langs"),
            "auto_subtitles": audio ? panel._pref("formats.auto_subtitles") : automatic,
            "embed_thumbnail": embedThumb.checked,
            "embed_metadata": embedMeta.checked,
            "embed_chapters": embedChapters.checked,
            "sponsorblock": analyzeController.siteKey === "youtube" || analyzeController.linkCount > 0
                ? sponsorBox.currentValue : "off",
            "live_from_start": analyzeController.liveStatus === "is_live" && fromStart.checked,
        }
    }

    // What Advanced holds, in a few words, while it is folded.
    function _advancedSummary() {
        var parts = []
        if (!panel.audio) {
            parts.push(codecBox.currentText.split(" (")[0])
            if (panel.hasSubtitles) parts.push("subtitles " + placementBox.currentText.toLowerCase())
        } else if (embedThumb.checked) {
            parts.push(coverBox.currentValue === "square" ? "square cover" : "cover in its own shape")
        }
        var inside = [embedThumb.checked ? (panel.audio ? "cover" : "thumbnail") : "",
                      embedMeta.checked ? "details" : "", embedChapters.checked ? "chapters" : ""]
            .filter(part => part.length > 0)
        parts.push(inside.length > 0 ? inside.join(", ") + " in the file" : "nothing extra in the file")
        if (sponsorRow.visible) parts.push("SponsorBlock " + (sponsorBox.currentValue === "off" ? "off"
                                                             : sponsorBox.currentValue === "mark" ? "marks sponsors" : "cuts sponsors"))
        return parts.join("  ·  ")
    }

    implicitHeight: Math.min(column.implicitHeight + 2 * Theme.spaceLg
                             + (actions.visible ? actions.implicitHeight + Theme.spaceMd : 0), panel.maxHeight)
    radius: Theme.radiusLarge
    color: Theme.surface
    border.width: 1
    border.color: Theme.border

    onVisibleChanged: if (visible) panel.reset()
    onKindChanged: {
        panel._resetEmbeds()
        analyzeController.refreshArchived(panel.options())
    }
    // A video's subtitles arrive once it is read; Preferences' languages are ticked in its list then,
    // unless the list was already changed by hand.
    onSubtitleModelChanged: if (!panel._subtitlesEdited) panel._resetSubtitles()

    // The keys the buttons' tooltips name: Esc closes the options, Ctrl+Enter downloads. An open list
    // takes Esc first, so Esc there closes only that.
    Shortcut {
        sequence: "Escape"
        enabled: panel.visible
        onActivated: closeButton.clicked()
    }
    Shortcut {
        sequences: ["Ctrl+Return", "Ctrl+Enter"]
        enabled: panel.visible && downloadButton.enabled
        onActivated: downloadButton.clicked()
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
                    visible: analyzeController.linkCount === 0
                    source: analyzeController.thumbnail
                    // Follows the Video | Audio switch: audio previews the song's square cover.
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
                        text: analyzeController.title || (analyzeController.busy ? "Reading the link..." : "")
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
                        text: [analyzeController.uploader, analyzeController.siteLabel,
                               analyzeController.busy ? analyzeController.status : "", analyzeController.details]
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

            // A video opened inside a playlist: that video, or every video of the playlist.
            FormRow {
                Layout.fillWidth: true
                visible: analyzeController.inPlaylist
                label: "Download"
                labelWidth: 110
                SegmentedChoice {
                    accessibleName: "Download this video or its whole playlist"
                    value: analyzeController.scope
                    options: [
                        {"label": "This video", "code": "video", "icon": "video",
                         "tip": "Only the video you opened"},
                        {"label": "Whole playlist", "code": "playlist", "icon": "list",
                         "tip": "Every video of the playlist it was opened in (you can untick some)"}
                    ]
                    onActivated: function (code) { analyzeController.analyze(analyzeController.link, code) }
                }
            }

            // Everyday choices
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
                    label: panel.audio ? "Audio format" : "Quality"
                    labelWidth: 110
                    StyledComboBox {
                        id: heightBox
                        Layout.fillWidth: true
                        visible: !panel.audio
                        model: analyzeController.heightOptions
                        accessibleName: "Highest quality"
                        toolTipText: "The best quality up to this one; measured on the shorter side, so it suits portrait videos too"
                        onActivated: analyzeController.refreshArchived(panel.options())
                    }
                    StyledComboBox {
                        id: audioBox
                        Layout.fillWidth: true
                        visible: panel.audio
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
                    visible: panel.audio
                    label: "Lyrics"
                    labelWidth: 110
                    AppSwitch {
                        id: lyricsSwitch
                        accessibleName: "Save lyrics"
                        toolTipText: "Save lyrics that follow along with the song, from the site's captions"
                            + (panel._pref("formats.lyrics_online") ? " or a free online lyrics service" : "")
                            + "; the audio player shows them line by line"
                    }
                }
                FormRow {
                    Layout.fillWidth: true
                    visible: !panel.audio
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
                    visible: !panel.audio
                    label: "Subtitles"
                    labelWidth: 110
                    LanguagePicker {
                        id: subtitlesPicker
                        Layout.fillWidth: true
                        enabled: panel.subtitleModel.length > 0
                        model: panel.subtitleModel
                        codes: panel.subtitleCodes
                        emptyText: panel.subtitleModel.length === 0 && analyzeController.ready
                            ? "This video has no subtitles" : "No subtitles"
                        accessibleName: "Subtitles"
                        toolTipText: panel.many ? "The languages to save; each video gets those it has"
                            : "The subtitles to save. Automatic ones are made by the site from the video's speech."
                        onEdited: function (codes) {
                            panel._subtitlesEdited = true
                            panel.subtitleCodes = codes
                        }
                    }
                }
                FormRow {
                    Layout.fillWidth: true
                    visible: !panel.audio && (analyzeController.audioTracks.length > 1 || panel.many)
                    label: "Audio tracks"
                    labelWidth: 110
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.spaceXs
                        StyledComboBox {
                            id: tracksBox
                            Layout.fillWidth: true
                            // "Every language" needs this video's own list, so lists get the first two.
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
                                delegate: AppCheckBox {
                                    required property var modelData
                                    text: modelData.label
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

            // Advanced choices, folded away with a summary of what they are set to.
            Disclosure {
                Layout.fillWidth: true
                visible: analyzeController.hasResult
                expanded: panel.advancedOpen
                onExpandedChanged: panel.advancedOpen = expanded
                summary: panel._advancedSummary()

                GridLayout {
                    Layout.fillWidth: true
                    columns: width > 760 ? 2 : 1
                    uniformCellWidths: true
                    columnSpacing: Theme.spaceXl
                    rowSpacing: Theme.spaceSm

                    FormRow {
                        Layout.fillWidth: true
                        visible: !panel.audio
                        label: "Compatibility"
                        labelWidth: 110
                        StyledComboBox {
                            id: codecBox
                            Layout.fillWidth: true
                            model: prefsController.options.codec
                            accessibleName: "Compatibility"
                            toolTipText: "Balanced takes the highest resolution; Plays everywhere picks what every player handles; Best quality may not play on older devices"
                        }
                    }
                    FormRow {
                        Layout.fillWidth: true
                        visible: !panel.audio && panel.hasSubtitles
                        label: "Subtitle placement"
                        labelWidth: 110
                        StyledComboBox {
                            id: placementBox
                            Layout.fillWidth: true
                            model: prefsController.options.subtitlePlacement
                            accessibleName: "Subtitle placement"
                            toolTipText: "Inside the video players can switch them on and off; separate files sit beside the video"
                        }
                    }
                    FormRow {
                        Layout.fillWidth: true
                        visible: !panel.audio && panel.hasSubtitles && placementBox.currentValue !== "embed"
                        label: "Subtitle file type"
                        labelWidth: 110
                        StyledComboBox {
                            id: subFormatBox
                            Layout.fillWidth: true
                            model: prefsController.options.subtitleFormat
                            accessibleName: "Subtitle file type"
                            toolTipText: "SRT works in most players; VTT keeps more of the text styling"
                        }
                    }
                    FormRow {
                        Layout.fillWidth: true
                        visible: !panel.audio && panel.many && panel.hasSubtitles
                        label: "Automatic captions"
                        labelWidth: 110
                        AppSwitch {
                            id: autoSubs
                            accessibleName: "Use automatic captions"
                            toolTipText: "Take the site's machine-made captions for a video without written subtitles in these languages"
                        }
                    }
                    FormRow {
                        Layout.fillWidth: true
                        visible: panel.audio && embedThumb.checked
                        label: "Cover shape"
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
                        label: "Save in the file"
                        labelWidth: 110
                        RowLayout {
                            spacing: Theme.spaceLg
                            AppCheckBox { id: embedThumb; text: panel.audio ? "Cover" : "Thumbnail"; toolTipText: "Show the thumbnail as the file's cover" }
                            AppCheckBox { id: embedMeta; text: "Details"; toolTipText: "Title, uploader, date, and description inside the file" }
                            AppCheckBox { id: embedChapters; text: "Chapters"; toolTipText: "Chapter marks players can jump to" }
                        }
                    }
                    FormRow {
                        id: sponsorRow
                        Layout.fillWidth: true
                        visible: analyzeController.siteKey === "youtube" || analyzeController.linkCount > 0
                        label: "SponsorBlock"
                        labelWidth: 110
                        StyledComboBox {
                            id: sponsorBox
                            Layout.fillWidth: true
                            model: prefsController.options.sponsorblock
                            accessibleName: "SponsorBlock"
                            toolTipText: "Mark or cut sponsor messages and reminders that SponsorBlock's community has tagged (YouTube)"
                        }
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

        Text {
            textFormat: Text.PlainText
            Layout.fillWidth: true
            visible: !analyzeController.ready
            text: "Download is ready once every video is listed."
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            color: Theme.textMuted
            elide: Text.ElideRight
        }
        Item { Layout.fillWidth: true; visible: analyzeController.ready }
        AppButton {
            id: downloadButton
            kind: "primary"
            enabled: analyzeController.ready
            text: analyzeController.liveStatus === "is_upcoming" ? "Wait and record"
                : analyzeController.liveStatus === "is_live" ? "Record" : "Download"
            iconName: analyzeController.liveStatus ? "live" : "download"
            toolTipText: "Download with the choices above (Ctrl+Enter)"
            onClicked: if (analyzeController.addToQueue(panel.options())) {
                panel.queued()
                panel.closed()
            }
        }
    }
}
