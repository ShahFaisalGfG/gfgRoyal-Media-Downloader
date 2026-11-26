// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Choices for extracting a downloaded video's audio, the same ones an audio download offers: format,
// bitrate, and lyrics (from the video's captions, then LRCLIB), with the cover's shape and what goes
// in the file under Advanced, as in Download options. They start from the audio preferences each time. Open it with forJob() for every
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
        embedCover.checked = prefsController.value("formats.audio_embed_cover")
        embedDetails.checked = prefsController.value("formats.audio_embed_metadata")
        embedChapters.checked = prefsController.value("formats.audio_embed_chapters")
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
            textFormat: Text.PlainText
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
            }
        }
        FormRow {
            label: "Lyrics"
            labelWidth: 120
            AppSwitch {
                id: lyricsSwitch
                accessibleName: "Save lyrics"
                toolTipText: "Save lyrics that follow along with the song, from the video's captions; the audio player shows them line by line"
            }
        }
        FormRow {
            visible: lyricsSwitch.checked
            label: "Look up online"
            labelWidth: 120
            AppSwitch {
                id: onlineSwitch
                accessibleName: "Look up lyrics online"
                toolTipText: "When the video has no captions, ask LRCLIB, a free online lyrics service; it is sent only the song's title, artist, album, and length"
            }
        }
        Disclosure {
            Layout.fillWidth: true
            summary: [embedCover.checked ? (coverBox.currentValue === "square" ? "square cover" : "cover in its own shape") : "",
                      [embedCover.checked ? "cover" : "", embedDetails.checked ? "details" : "",
                       embedChapters.checked ? "chapters" : ""].filter(part => part.length > 0).join(", ")]
                .filter(part => part.length > 0).join("  ·  ") || "nothing extra in the file"

            FormRow {
                Layout.fillWidth: true
                label: "Save in the file"
                labelWidth: 120
                RowLayout {
                    spacing: Theme.spaceLg
                    AppCheckBox { id: embedCover; text: "Cover" }
                    AppCheckBox { id: embedDetails; text: "Details"; toolTipText: "Title, artist, date, and description inside the file" }
                    AppCheckBox { id: embedChapters; text: "Chapters" }
                }
            }
            FormRow {
                Layout.fillWidth: true
                visible: embedCover.checked
                label: "Cover shape"
                labelWidth: 120
                StyledComboBox {
                    id: coverBox
                    Layout.fillWidth: true
                    model: prefsController.options.cover
                    accessibleName: "Cover shape"
                }
            }
        }
        Text {
            textFormat: Text.PlainText
            Layout.fillWidth: true
            text: "The song is saved in your audio folder, inside a folder named after the playlist when the video came from one."
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            color: Theme.textMuted
            wrapMode: Text.WordWrap
        }
    }
}
