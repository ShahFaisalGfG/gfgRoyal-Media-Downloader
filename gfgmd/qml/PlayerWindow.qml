// qmllint disable unqualified
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import QtMultimedia

import "components"

// The video player: its own window, so downloads stay in view. Controls hide while the video plays
// and the pointer rests, unless one of them has keyboard focus; they come back on any movement or
// key, Tab included. Playback resumes where it stopped
// last time. Keys: Space or K play/pause, J and L 10 s back and ahead, Left and Right 5 s, Up and
// Down volume, M mute, F fullscreen (Esc leaves it), C subtitles, [ and ] speed, P and N previous
// and next, Home and End.
AppWindow {
    id: playerWin

    width: playerController.videoWidth
    height: playerController.videoHeight
    minimumWidth: 480
    minimumHeight: 320
    visible: false
    title: playerController.videoTitle.length > 0 ? playerController.videoTitle : "Player"

    readonly property bool full: playerWin.visibility === Window.FullScreen
    readonly property bool playing: player.playbackState === MediaPlayer.PlayingState
    property bool controlsShown: true
    property string _path: ""
    property real _pendingSeek: 0
    property bool _onTop: false

    function showControls() {
        playerWin.controlsShown = true
        hideTimer.restart()
    }
    function toggleFull() {
        if (playerWin.full) playerWin.showNormal()
        else playerWin.showFullScreen()
        playerWin.showControls()
    }
    function seekBy(ms) {
        player.position = Math.max(0, Math.min(player.duration, player.position + ms))
        playerWin.showControls()
    }
    function setVolume(volume) {
        playerController.setVolume(Math.max(0, Math.min(1, volume)))
        if (playerController.muted && volume > 0) playerController.setMuted(false)
        playerWin.showControls()
    }
    function stepSpeed(step) {
        var speeds = playerController.speeds
        var index = speeds.indexOf(playerController.speed)
        playerController.setSpeed(speeds[Math.max(0, Math.min(speeds.length - 1, (index < 0 ? 3 : index) + step))])
        playerWin.showControls()
    }
    function savePosition() {
        if (playerWin._path.length > 0 && player.duration > 0)
            playerController.savePosition(playerWin._path, player.position, player.duration)
    }
    // Load the controller's current video, remembering where the previous one stopped.
    function load() {
        playerWin.savePosition()
        playerWin._path = playerController.videoPath
        playerWin._pendingSeek = playerController.resumeAt(playerWin._path)
        errorBox.text = ""
        player.source = playerController.videoUrl
        player.play()
        playerWin.showControls()
    }
    function trackChoices(tracks) {
        var names = []
        for (var i = 0; i < tracks.length; ++i)
            names.push(playerController.trackLabel(tracks[i].stringValue(MediaMetaData.Title) || "",
                                                   tracks[i].value(MediaMetaData.Language) || 0, i + 1))
        return names
    }

    // Let go of the file: a stopped player keeps it open (and Windows can't delete it) until its
    // source is cleared.
    function release() {
        player.stop()
        player.source = ""
        playerWin._path = ""
    }

    onClosing: {
        playerWin.savePosition()
        playerWin.release()
        playerController.closeVideo()
        if (!playerWin.full) playerController.saveVideoSize(playerWin.width, playerWin.height)
    }

    Connections {
        target: playerController
        function onVideoRequested() {
            playerWin.load()
            playerWin.show()
            playerWin.raise()
            playerWin.requestActivate()
            stage.forceActiveFocus()
        }
        // The video is about to be deleted (or the controller forgot it): close without saving its place.
        function onVideoChanged() {
            if (playerController.videoPath.length === 0 && playerWin._path.length > 0) {
                playerWin.release()
                playerWin.close()
            }
        }
    }

    MediaPlayer {
        id: player
        videoOutput: videoOut
        audioOutput: AudioOutput {
            volume: playerController.volume
            muted: playerController.muted
        }
        playbackRate: playerController.speed
        loops: loopButton.checked ? MediaPlayer.Infinite : 1
        onMediaStatusChanged: {
            if ((player.mediaStatus === MediaPlayer.LoadedMedia || player.mediaStatus === MediaPlayer.BufferedMedia)
                    && playerWin._pendingSeek > 0 && player.seekable) {
                player.position = playerWin._pendingSeek
                playerWin._pendingSeek = 0
            }
            if (player.mediaStatus === MediaPlayer.EndOfMedia) {
                playerController.savePosition(playerWin._path, player.duration, player.duration)
                playerWin.showControls()
                if (playerController.hasNextVideo) playerController.stepVideo(1)
            }
        }
        // The player's own error text is for the log; the window says what to do instead.
        onErrorOccurred: function (error, errorString) {
            playerController.logPlaybackError(playerWin._path, errorString)
            errorBox.text = "This video can't be played here. Try opening it in another player."
        }
        onPlaybackStateChanged: playerWin.showControls()
        // Portrait videos (Shorts, TikToks, Reels) get a portrait window the first time they show.
        onMetaDataChanged: {
            var size = player.metaData.value(MediaMetaData.Resolution)
            if (!size || playerWin.full || size.width <= 0 || size.height <= size.width) return
            var area = playerWin.screenArea()
            var height = Math.min(area.height * 0.85, size.height)
            playerWin.height = Math.max(playerWin.minimumHeight, height)
            playerWin.width = Math.max(playerWin.minimumWidth, Math.round(height * size.width / size.height))
            playerWin.placeOnScreen()
        }
    }

    // Saves the position now and then, so a crash or power cut resumes close to where it stopped.
    Timer { interval: 5000; repeat: true; running: playerWin.playing; onTriggered: playerWin.savePosition() }
    Timer {
        id: hideTimer
        interval: 2500
        onTriggered: if (playerWin.playing && !controls.containsMouse && !controls.focusInside) playerWin.controlsShown = false
    }

    // The normal place of the video; in fullscreen the stage moves over the title bar.
    Item { id: normalHolder; anchors.fill: parent }

    Item {
        id: stage
        parent: playerWin.full ? playerWin.contentItem : normalHolder
        anchors.fill: parent
        z: 200
        focus: true

        Rectangle { anchors.fill: parent; color: "#000000" }

        VideoOutput {
            id: videoOut
            anchors.fill: parent
            fillMode: VideoOutput.PreserveAspectFit
        }

        // Pointer movement shows the controls; a click plays or pauses; a double click is fullscreen only.
        // A click waits the system's double-click time before pausing, so a double click doesn't also
        // pause (and play again) the video.
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: playerWin.controlsShown || !playerWin.full ? Qt.ArrowCursor : Qt.BlankCursor
            onPositionChanged: playerWin.showControls()
            onClicked: { stage.forceActiveFocus(); clickTimer.restart() }
            onDoubleClicked: { clickTimer.stop(); playerWin.toggleFull() }
        }
        Timer {
            id: clickTimer
            interval: Application.styleHints.mouseDoubleClickInterval
            onTriggered: playerWin.playing ? player.pause() : player.play()
        }

        // A subtitle file saved beside the video (embedded tracks are drawn by the video output).
        Text {
            textFormat: Text.PlainText
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: playerWin.controlsShown ? controls.height + Theme.spaceMd : Theme.spaceXl
            width: parent.width * 0.86
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            visible: text.length > 0
            text: playerController.captionFile >= 0 ? playerController.captionAt(player.position) : ""
            font.family: Theme.fontFamily
            font.pixelSize: Math.max(16, Math.round(stage.height / 22))
            font.weight: Font.DemiBold
            color: Theme.overlayText
            style: Text.Outline
            styleColor: "#000000"
        }

        ColumnLayout {
            anchors.centerIn: parent
            width: Math.min(parent.width - 2 * Theme.spaceXl, 460)
            visible: errorBox.text.length > 0
            spacing: Theme.spaceMd
            Text {
                id: errorBox
                textFormat: Text.PlainText
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                color: Theme.overlayText
            }
            AppButton {
                Layout.alignment: Qt.AlignHCenter
                text: "Open in another player"
                iconName: "openExternal"
                onClicked: playerController.openInSystem(playerWin._path)
            }
        }

        Rectangle {
            id: controls
            readonly property bool containsMouse: controlsHover.hovered
            // Keyboard focus on one of the bar's buttons or sliders keeps the bar shown.
            readonly property bool focusInside: {
                for (var item = playerWin.activeFocusItem; item; item = item.parent)
                    if (item === controls) return true
                return false
            }
            onFocusInsideChanged: playerWin.showControls()
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: controlColumn.implicitHeight + 2 * Theme.spaceMd
            opacity: playerWin.controlsShown ? 1 : 0
            // Visible as soon as it is asked for, before the fade starts, so Tab can reach its controls.
            visible: playerWin.controlsShown || opacity > 0
            Behavior on opacity { NumberAnimation { duration: Theme.motionMedium } }
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#00000000" }
                GradientStop { position: 0.35; color: "#99000000" }
                GradientStop { position: 1.0; color: "#cc000000" }
            }
            HoverHandler { id: controlsHover }

            ColumnLayout {
                id: controlColumn
                anchors.fill: parent
                anchors.margins: Theme.spaceMd
                anchors.topMargin: Theme.spaceXl
                spacing: Theme.spaceXs

                SeekBar {
                    Layout.fillWidth: true
                    light: true
                    position: player.position
                    duration: player.duration
                    seekable: player.seekable
                    onSeek: function (ms) { player.position = ms; playerWin.showControls() }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spaceXs

                    PlayerButton { iconName: "previous"; toolTipText: "Previous video (P)"; enabled: playerController.hasPreviousVideo; onClicked: playerController.stepVideo(-1) }
                    PlayerButton { iconName: "rewind"; toolTipText: "Back 10 seconds (J)"; onClicked: playerWin.seekBy(-10000) }
                    PlayerButton {
                        iconName: playerWin.playing ? "pause" : "play"
                        toolTipText: playerWin.playing ? "Pause (Space)" : "Play (Space)"
                        onClicked: playerWin.playing ? player.pause() : player.play()
                    }
                    PlayerButton { iconName: "forward"; toolTipText: "Ahead 10 seconds (L)"; onClicked: playerWin.seekBy(10000) }
                    PlayerButton { iconName: "next"; toolTipText: "Next video (N)"; enabled: playerController.hasNextVideo; onClicked: playerController.stepVideo(1) }
                    PlayerButton {
                        iconName: playerController.muted || playerController.volume === 0 ? "mute" : "volume"
                        toolTipText: playerController.muted ? "Unmute (M)" : "Mute (M)"
                        onClicked: playerController.setMuted(!playerController.muted)
                    }
                    Slider {
                        Layout.preferredWidth: 96
                        from: 0
                        to: 1
                        value: playerController.muted ? 0 : playerController.volume
                        focusPolicy: Qt.TabFocus
                        Accessible.name: "Volume"
                        onMoved: playerWin.setVolume(value)
                    }
                    Text {
                        textFormat: Text.PlainText
                        Layout.fillWidth: true
                        text: playerWin.title
                        elide: Text.ElideRight
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontCaption
                        color: Theme.overlayText
                        visible: playerWin.full
                    }
                    Item { Layout.fillWidth: !playerWin.full }
                    PlayerButton {
                        id: speedButton
                        text: playerController.speed + "×"
                        toolTipText: "Speed ([ slower, ] faster)"
                        onClicked: speedMenu.openAbove(speedButton)
                    }
                    PlayerButton {
                        id: audioButton
                        iconName: "audio"
                        toolTipText: "Audio track"
                        visible: player.audioTracks.length > 1
                        onClicked: audioMenu.openAbove(audioButton)
                    }
                    PlayerButton {
                        id: subtitleButton
                        iconName: "subtitles"
                        toolTipText: "Subtitles (C)"
                        checked: player.activeSubtitleTrack >= 0 || playerController.captionFile >= 0
                        visible: player.subtitleTracks.length + playerController.captionFiles.length > 0
                        onClicked: subtitleMenu.openAbove(subtitleButton)
                    }
                    PlayerButton { id: loopButton; iconName: "repeatOne"; checkable: true; toolTipText: "Play this video again and again" }
                    PlayerButton {
                        iconName: playerWin._onTop ? "unpin" : "pin"
                        toolTipText: playerWin._onTop ? "Stop keeping the player on top" : "Keep the player on top of other windows"
                        visible: !playerWin.full
                        onClicked: {
                            playerWin._onTop = !playerWin._onTop
                            playerWin.flags = playerWin._onTop ? (Qt.FramelessWindowHint | Qt.Window | Qt.WindowStaysOnTopHint)
                                                               : (Qt.FramelessWindowHint | Qt.Window)
                        }
                    }
                    PlayerButton {
                        iconName: playerWin.full ? "exitFullscreen" : "fullscreen"
                        toolTipText: playerWin.full ? "Leave fullscreen (F or Esc)" : "Fullscreen (F)"
                        onClicked: playerWin.toggleFull()
                    }
                }
            }
        }

        Keys.onPressed: function (event) {
            var handled = true
            switch (event.key) {
            case Qt.Key_Space: case Qt.Key_K: case Qt.Key_MediaTogglePlayPause: case Qt.Key_MediaPlay:
                playerWin.playing ? player.pause() : player.play(); break
            case Qt.Key_J: playerWin.seekBy(-10000); break
            case Qt.Key_L: playerWin.seekBy(10000); break
            case Qt.Key_Left: playerWin.seekBy(-5000); break
            case Qt.Key_Right: playerWin.seekBy(5000); break
            case Qt.Key_Up: playerWin.setVolume(playerController.volume + 0.05); break
            case Qt.Key_Down: playerWin.setVolume(playerController.volume - 0.05); break
            case Qt.Key_M: playerController.setMuted(!playerController.muted); break
            case Qt.Key_F: playerWin.toggleFull(); break
            case Qt.Key_Escape: if (playerWin.full) playerWin.showNormal(); else handled = false; break
            case Qt.Key_C: subtitleMenu.cycle(); break
            case Qt.Key_BracketLeft: playerWin.stepSpeed(-1); break
            case Qt.Key_BracketRight: playerWin.stepSpeed(1); break
            case Qt.Key_N: case Qt.Key_MediaNext: playerController.stepVideo(1); break
            case Qt.Key_P: case Qt.Key_MediaPrevious: playerController.stepVideo(-1); break
            case Qt.Key_Home: player.position = 0; break
            case Qt.Key_End: player.position = Math.max(0, player.duration - 1000); break
            // Show the hidden controls first, then let Tab move focus into them.
            case Qt.Key_Tab: case Qt.Key_Backtab: playerWin.showControls(); handled = false; break
            default: handled = false
            }
            if (handled) {
                playerWin.showControls()
                event.accepted = true
            }
        }
    }

    ChoiceMenu {
        id: speedMenu
        parent: stage
        title: "Speed"
        choices: playerController.speeds.map(function (speed) { return speed === 1 ? "Normal" : speed + "×" })
        current: playerController.speeds.indexOf(playerController.speed)
        onChosen: function (index) { playerController.setSpeed(playerController.speeds[index]) }
    }

    ChoiceMenu {
        id: audioMenu
        parent: stage
        title: "Audio track"
        choices: playerWin.trackChoices(player.audioTracks)
        current: player.activeAudioTrack
        onChosen: function (index) { player.activeAudioTrack = index }
    }

    // Embedded subtitle tracks first, then subtitle files saved beside the video.
    ChoiceMenu {
        id: subtitleMenu
        readonly property int embedded: player.subtitleTracks.length
        function cycle() {
            var count = 1 + subtitleMenu.embedded + playerController.captionFiles.length
            subtitleMenu.pick((subtitleMenu.current + 1) % count)
        }
        function pick(index) {
            player.activeSubtitleTrack = index >= 1 && index <= subtitleMenu.embedded ? index - 1 : -1
            playerController.setCaptionFile(index > subtitleMenu.embedded ? index - 1 - subtitleMenu.embedded : -1)
        }
        parent: stage
        title: "Subtitles"
        choices: ["Off"].concat(playerWin.trackChoices(player.subtitleTracks), playerController.captionFiles)
        current: player.activeSubtitleTrack >= 0 ? player.activeSubtitleTrack + 1
                 : playerController.captionFile >= 0 ? 1 + subtitleMenu.embedded + playerController.captionFile : 0
        onChosen: function (index) { subtitleMenu.pick(index) }
    }

    // The control-bar buttons; a click keeps the controls shown.
    component PlayerButton: OverlayButton { onClicked: playerWin.showControls() }
}
