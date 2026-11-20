// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Choices for extracting a downloaded video's audio, the same ones an audio download offers: format,
// bitrate, cover and its shape, lyrics (from the video's captions, then LRCLIB), and what goes in
// the file. They start from the audio preferences each time. Open it with forJob() for every
// video a download saved, or forVideos() for library videos (songs among them are left out).
AppDialog {
    id: dialog

    property int jobId: -1
    property var historyIds: []
    readonly property bool lossless: prefsController.losslessAudio.indexOf(formatBox.currentValue) >= 0

    function _open(title) {
        name.text = title
        formatBox.value = prefsController.value("formats.audio_format")
        qualityBox.value = prefsController.value("formats.audio_quality")
        coverBox.value = prefsController.value("formats.cover")
        lyricsSwitch.checked = prefsController.value("formats.lyrics")
        onlineSwitch.checked = prefsController.value("formats.lyrics_online")
        embedCover.checked = prefsController.value("formats.embed_thumbnail")
        embedDetails.checked = prefsController.value("formats.embed_metadata")
        embedChapters.checked = prefsController.value("formats.embed_chapters")
        dialog.open()
    }

    function forJob(jobId, title) {
        dialog.jobId = jobId
        dialog.historyIds = []
        dialog._open(title)
    }

    function forVideos(historyIds, title) {
        dialog.historyIds = historyIds
        dialog.jobId = -1
        dialog._open(title)
    }

    function choices() {
        return {
            "audio_format": formatBox.currentValue,
            "audio_quality": qualityBox.currentValue,
            "cover": coverBox.currentValue,
            "lyrics": lyricsSwitch.checked,
            "lyrics_online": onlineSwitch.checked,
            "embed_thumbnail": embedCover.checked,
            "embed_metadata": embedDetails.checked,
            "embed_chapters": embedChapters.checked,
        }
    }

    title: "Extract audio"
    standardButtons: Dialog.Ok | Dialog.Cancel
    defaultButton: Dialog.Ok
    // Wide enough that every row keeps its label beside the control (FormRow stacks below 480 px).
    width: Math.min(parent ? parent.width - 2 * Theme.spaceXl : 580, 580)
    Component.onCompleted: dialog.standardButton(Dialog.Ok).text = "Extract"
    onAccepted: {
        if (dialog.jobId >= 0) queueController.extractJobAudio(dialog.jobId, dialog.choices())
        else queueController.extractAudio(dialog.historyIds, dialog.choices())
    }

    ColumnLayout {
        width: parent.width
        spacing: Theme.spaceSm

        Text {
            id: name
            Layout.fillWidth: true
            Layout.bottomMargin: Theme.spaceXs
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            font.weight: Font.DemiBold
            color: Theme.text
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
        }

        FormRow {
            label: "Audio format"
            labelWidth: 120
            StyledComboBox {
                id: formatBox
                Layout.fillWidth: true
                model: prefsController.options.audio
                accessibleName: "Audio format"
                toolTipText: "MP3 plays everywhere; FLAC and WAV are lossless; Original keeps the video's own sound unconverted"
            }
        }
        FormRow {
            visible: !dialog.lossless
            label: "Audio quality"
            labelWidth: 120
            StyledComboBox {
                id: qualityBox
                Layout.fillWidth: true
                model: prefsController.options.audioQuality
                accessibleName: "Audio quality"
                toolTipText: "Videos carry about 128-256 kbps of sound; a higher bitrate keeps all of it but can't add detail"
            }
        }
        FormRow {
            visible: embedCover.checked
            label: "Cover"
            labelWidth: 120
            StyledComboBox {
                id: coverBox
                Layout.fillWidth: true
                model: prefsController.options.cover
                accessibleName: "Cover shape"
                toolTipText: "The video's thumbnail becomes the song's cover; square crops it like an album cover"
            }
        }
        FormRow {
            label: "Lyrics"
            labelWidth: 120
            AppSwitch {
                id: lyricsSwitch
                accessibleName: "Save lyrics"
                toolTipText: "Save timed lyrics (.lrc) from the video's caption files; the audio player shows them line by line"
            }
        }
        FormRow {
            visible: lyricsSwitch.checked
            label: "Look up online"
            labelWidth: 120
            AppSwitch {
                id: onlineSwitch
                accessibleName: "Look up lyrics online"
                toolTipText: "When the video has no captions, ask LRCLIB for the lyrics; it is sent only the song's title, artist, album, and length"
            }
        }
        FormRow {
            label: "Embed"
            labelWidth: 120
            RowLayout {
                spacing: Theme.spaceLg
                CheckBox { id: embedCover; text: "Cover"; font.family: Theme.fontFamily; ToolTip.text: "Show the thumbnail as the song's cover (WAV gets it as a picture beside the file)"; ToolTip.visible: hovered }
                CheckBox { id: embedDetails; text: "Details"; font.family: Theme.fontFamily; ToolTip.text: "Title, artist, date, and description inside the file"; ToolTip.visible: hovered }
                CheckBox { id: embedChapters; text: "Chapters"; font.family: Theme.fontFamily; ToolTip.text: "The video's chapter marks, which players can jump to"; ToolTip.visible: hovered }
            }
        }
        Text {
            Layout.fillWidth: true
            text: "The song takes the video's place in the audio folder: a playlist video's goes in a folder of the playlist's name."
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            color: Theme.textMuted
            wrapMode: Text.WordWrap
        }
    }
}
