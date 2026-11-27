// qmllint disable unqualified
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

import "components"

// The photo viewer: its own window, like the video player. A picture opens fitted to the window
// (never past its own size), with the list's other pictures in a filmstrip. The wheel zooms where
// the pointer is and dragging moves a zoomed picture. Keys: Left and Right (or Page Up and Page
// Down) previous and next, Home and End, + and - zoom, 0 fit, R turn the view (Shift+R the other
// way), Space slideshow, F fullscreen (Esc leaves it), Delete to the Recycle Bin.
// In fullscreen and during a slideshow the controls hide while the pointer rests.
AppWindow {
    id: viewer

    width: 1000
    height: 720
    minimumWidth: 480
    minimumHeight: 360
    visible: false
    title: playerController.photoTitle.length > 0 ? playerController.photoTitle : "Pictures"

    readonly property bool full: viewer.visibility === Window.FullScreen
    readonly property bool many: playerController.photoCount > 1
    readonly property bool turned: viewer.turn % 180 !== 0
    // 1 fits the picture in the window; up to 8 times that.
    property real zoom: 1
    property int turn: 0
    property real panX: 0
    property real panY: 0
    property bool slideshow: false
    property bool controlsShown: true
    readonly property Image picture: playerController.photoAnimated ? animated : still
    // The picture's own size as turned, and the scale that fits it in the stage (at most 1:1).
    readonly property real naturalWidth: viewer.turned ? viewer.picture.implicitHeight : viewer.picture.implicitWidth
    readonly property real naturalHeight: viewer.turned ? viewer.picture.implicitWidth : viewer.picture.implicitHeight
    readonly property real fitScale: viewer.naturalWidth > 0 && viewer.naturalHeight > 0
        ? Math.min(1, stage.width / viewer.naturalWidth, stage.height / viewer.naturalHeight) : 1

    function showControls() {
        viewer.controlsShown = true
        hideTimer.restart()
    }
    function toggleFull() {
        if (viewer.full) viewer.showNormal()
        else viewer.showFullScreen()
        viewer.showControls()
    }
    // Zoom keeping the point (x, y) of the stage where it is (the stage's middle by default).
    function zoomTo(value, x, y) {
        var px = x === undefined ? stage.width / 2 : x
        var py = y === undefined ? stage.height / 2 : y
        var zoom = Math.max(1, Math.min(8, value))
        var ratio = zoom / viewer.zoom
        var dx = px - (stage.width / 2 + viewer.panX)
        var dy = py - (stage.height / 2 + viewer.panY)
        viewer.zoom = zoom
        viewer.panX = px - dx * ratio - stage.width / 2
        viewer.panY = py - dy * ratio - stage.height / 2
        viewer.clampPan()
        viewer.showControls()
    }
    // Keep a zoomed picture covering the stage: it moves no further than its edges.
    function clampPan() {
        var spareX = Math.max(0, (frame.width - stage.width) / 2)
        var spareY = Math.max(0, (frame.height - stage.height) / 2)
        viewer.panX = Math.max(-spareX, Math.min(spareX, viewer.panX))
        viewer.panY = Math.max(-spareY, Math.min(spareY, viewer.panY))
    }
    function fit() {
        viewer.zoom = 1
        viewer.panX = 0
        viewer.panY = 0
    }
    function step(by) {
        playerController.stepPhoto(by, false)
        viewer.showControls()
    }
    // Let go of the file, so Windows can move it to the Recycle Bin.
    function release() {
        viewer.slideshow = false
        still.source = ""
        animated.source = ""
    }

    onClosing: {
        viewer.release()
        playerController.closePhoto()
    }

    Connections {
        target: playerController
        function onPhotoRequested() {
            viewer.show()
            viewer.raise()
            viewer.requestActivate()
            stage.forceActiveFocus()
            viewer.showControls()
        }
        // Another picture: it opens fitted and upright. None left (deleted): the viewer closes.
        function onPhotoChanged() {
            viewer.fit()
            viewer.turn = 0
            if (playerController.photoCount < 2) viewer.slideshow = false
            if (playerController.photoPath.length === 0 && viewer.visible) {
                viewer.release()
                viewer.close()
            }
        }
    }

    Timer {
        interval: 4000
        repeat: true
        running: viewer.slideshow && viewer.visible
        onTriggered: playerController.stepPhoto(1, true)
    }
    Timer {
        id: hideTimer
        interval: 2500
        onTriggered: if ((viewer.full || viewer.slideshow) && !controls.containsMouse && !controls.focusInside)
                         viewer.controlsShown = false
    }

    // The normal place of the picture; in fullscreen the stage moves over the title bar.
    Item { id: normalHolder; anchors.fill: parent }

    Item {
        id: stage
        parent: viewer.full ? viewer.contentItem : normalHolder
        anchors.fill: parent
        z: 200
        focus: true

        Rectangle { anchors.fill: parent; color: "#000000" }

        // The picture, centred and moved by `pan` when zoomed past the stage.
        Item {
            id: frame
            x: (stage.width - frame.width) / 2 + viewer.panX
            y: (stage.height - frame.height) / 2 + viewer.panY
            width: viewer.naturalWidth * viewer.fitScale * viewer.zoom
            height: viewer.naturalHeight * viewer.fitScale * viewer.zoom

            Image {
                id: still
                anchors.centerIn: parent
                width: viewer.turned ? frame.height : frame.width
                height: viewer.turned ? frame.width : frame.height
                rotation: viewer.turn
                visible: !playerController.photoAnimated
                source: playerController.photoAnimated ? "" : playerController.photoUrl
                asynchronous: true
                autoTransform: true  // the camera's own orientation
                smooth: true
                mipmap: true
                Accessible.role: Accessible.Graphic
                Accessible.name: viewer.title
            }
            AnimatedImage {
                id: animated
                anchors.centerIn: parent
                width: viewer.turned ? frame.height : frame.width
                height: viewer.turned ? frame.width : frame.height
                rotation: viewer.turn
                visible: playerController.photoAnimated
                source: playerController.photoAnimated ? playerController.photoUrl : ""
                asynchronous: true
                smooth: true
                Accessible.role: Accessible.Graphic
                Accessible.name: viewer.title
            }
        }

        // Pointer movement shows the controls, the wheel zooms where the pointer is, dragging moves
        // a zoomed picture, and a double click is fullscreen.
        Item {
            id: surface
            anchors.fill: parent
            onWidthChanged: viewer.clampPan()
            onHeightChanged: viewer.clampPan()

            HoverHandler {
                cursorShape: viewer.zoom > 1 ? (drag.active ? Qt.ClosedHandCursor : Qt.OpenHandCursor)
                    : viewer.controlsShown || !viewer.full ? Qt.ArrowCursor : Qt.BlankCursor
                onPointChanged: viewer.showControls()
            }
            TapHandler {
                onTapped: stage.forceActiveFocus()
                onDoubleTapped: viewer.toggleFull()
            }
            WheelHandler {
                acceptedModifiers: Qt.KeyboardModifierMask
                onWheel: function (event) {
                    if (event.angleDelta.y !== 0)
                        viewer.zoomTo(viewer.zoom * (event.angleDelta.y > 0 ? 1.25 : 0.8), event.x, event.y)
                }
            }
            DragHandler {
                id: drag
                property real startX: 0
                property real startY: 0
                target: null
                enabled: viewer.zoom > 1
                onActiveChanged: if (active) { drag.startX = viewer.panX; drag.startY = viewer.panY }
                onTranslationChanged: {
                    viewer.panX = drag.startX + drag.translation.x
                    viewer.panY = drag.startY + drag.translation.y
                    viewer.clampPan()
                }
            }
        }

        BusyIndicator {
            anchors.centerIn: parent
            running: viewer.picture.status === Image.Loading
            visible: running
        }

        ColumnLayout {
            anchors.centerIn: parent
            width: Math.min(parent.width - 2 * Theme.spaceXl, 460)
            visible: viewer.picture.status === Image.Error
            spacing: Theme.spaceMd
            Text {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                text: "This picture can't be shown here. Try opening it in another app."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                color: Theme.overlayText
            }
            AppButton {
                Layout.alignment: Qt.AlignHCenter
                text: "Open in another app"
                iconName: "openExternal"
                onClicked: playerController.openInSystem(playerController.photoPath)
            }
        }

        Rectangle {
            id: controls
            readonly property bool containsMouse: controlsHover.hovered
            // Keyboard focus on one of the bar's buttons keeps the bar shown.
            readonly property bool focusInside: {
                for (var item = viewer.activeFocusItem; item; item = item.parent)
                    if (item === controls) return true
                return false
            }
            onFocusInsideChanged: viewer.showControls()
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: controlColumn.implicitHeight + 2 * Theme.spaceMd
            opacity: viewer.controlsShown ? 1 : 0
            // Visible as soon as it is asked for, before the fade starts, so Tab can reach its controls.
            visible: viewer.controlsShown || opacity > 0
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
                spacing: Theme.spaceSm

                // The filmstrip: the list's pictures, the one shown marked; a click shows it.
                ListView {
                    id: strip
                    Layout.fillWidth: true
                    Layout.preferredHeight: 52
                    visible: viewer.many
                    orientation: ListView.Horizontal
                    spacing: Theme.spaceXs
                    clip: true
                    model: playerController.photoUrls
                    currentIndex: playerController.photoIndex
                    highlightFollowsCurrentItem: true
                    highlightMoveDuration: Theme.motionMedium
                    preferredHighlightBegin: strip.width / 2 - 36
                    preferredHighlightEnd: strip.width / 2 + 36
                    highlightRangeMode: ListView.ApplyRange
                    boundsBehavior: Flickable.StopAtBounds
                    Accessible.role: Accessible.List
                    Accessible.name: "Pictures"
                    delegate: AbstractButton {
                        id: tile
                        required property string modelData
                        required property int index
                        readonly property bool shown: tile.index === playerController.photoIndex
                        width: 72
                        height: 52
                        hoverEnabled: true
                        focusPolicy: Qt.NoFocus
                        Accessible.role: Accessible.Button
                        Accessible.name: "Picture " + (tile.index + 1) + " of " + playerController.photoCount
                        onClicked: { playerController.showPhoto(tile.index); viewer.showControls() }
                        background: Rectangle {
                            radius: Theme.radius
                            color: "#33ffffff"
                            border.width: tile.shown ? 2 : tile.hovered ? 1 : 0
                            border.color: tile.shown ? Theme.overlayAccent : Theme.overlayText
                            Behavior on border.width { NumberAnimation { duration: Theme.motionFast } }
                        }
                        contentItem: Image {
                            anchors.fill: parent
                            anchors.margins: 2
                            source: tile.modelData
                            sourceSize.height: 104
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                            opacity: tile.shown || tile.hovered ? 1 : 0.7
                            Behavior on opacity { NumberAnimation { duration: Theme.motionFast } }
                            Accessible.ignored: true
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spaceXs

                    ViewerButton { iconName: "previous"; toolTipText: "Previous picture (Left)"; enabled: playerController.photoIndex > 0; onClicked: viewer.step(-1) }
                    ViewerButton {
                        iconName: viewer.slideshow ? "pause" : "slideshow"
                        toolTipText: viewer.slideshow ? "Stop the slideshow (Space)" : "Slideshow (Space)"
                        visible: viewer.many
                        onClicked: viewer.slideshow = !viewer.slideshow
                    }
                    ViewerButton { iconName: "next"; toolTipText: "Next picture (Right)"; enabled: playerController.photoIndex < playerController.photoCount - 1; onClicked: viewer.step(1) }
                    Text {
                        textFormat: Text.PlainText
                        visible: viewer.many
                        text: (playerController.photoIndex + 1) + " of " + playerController.photoCount
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontCaption
                        color: Theme.overlayText
                        leftPadding: Theme.spaceSm
                        rightPadding: Theme.spaceSm
                    }
                    Text {
                        textFormat: Text.PlainText
                        Layout.fillWidth: true
                        text: viewer.full ? viewer.title : ""
                        elide: Text.ElideRight
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontCaption
                        color: Theme.overlayText
                    }
                    ViewerButton { iconName: "zoomOut"; toolTipText: "Zoom out (-)"; enabled: viewer.zoom > 1; onClicked: viewer.zoomTo(viewer.zoom / 1.5) }
                    ViewerButton {
                        text: Math.round(viewer.fitScale * viewer.zoom * 100) + "%"
                        toolTipText: "Fit to the window (0)"
                        onClicked: viewer.fit()
                    }
                    ViewerButton { iconName: "zoomIn"; toolTipText: "Zoom in (+)"; enabled: viewer.zoom < 8; onClicked: viewer.zoomTo(viewer.zoom * 1.5) }
                    ViewerButton { iconName: "rotate"; toolTipText: "Turn the view (R)"; onClicked: viewer.turn = (viewer.turn + 90) % 360 }
                    ViewerButton { iconName: "openExternal"; toolTipText: "Open in another app"; onClicked: playerController.openInSystem(playerController.photoPath) }
                    ViewerButton { iconName: "folderOpen"; toolTipText: "Show in folder"; onClicked: appController.revealFile(playerController.photoPath) }
                    ViewerButton {
                        iconName: "delete"
                        toolTipText: "Move to the Recycle Bin (Delete)"
                        visible: playerController.photoHistoryId > 0
                        onClicked: deleteDialog.open()
                    }
                    ViewerButton {
                        iconName: viewer.full ? "exitFullscreen" : "fullscreen"
                        toolTipText: viewer.full ? "Leave fullscreen (F or Esc)" : "Fullscreen (F)"
                        onClicked: viewer.toggleFull()
                    }
                }
            }
        }

        Keys.onPressed: function (event) {
            var handled = true
            var ctrl = (event.modifiers & Qt.ControlModifier) !== 0
            switch (event.key) {
            case Qt.Key_Left: case Qt.Key_PageUp: case Qt.Key_MediaPrevious: viewer.step(-1); break
            case Qt.Key_Right: case Qt.Key_PageDown: case Qt.Key_MediaNext: viewer.step(1); break
            case Qt.Key_Home: playerController.showPhoto(0); break
            case Qt.Key_End: playerController.showPhoto(playerController.photoCount - 1); break
            case Qt.Key_Plus: case Qt.Key_Equal: viewer.zoomTo(viewer.zoom * 1.5); break
            case Qt.Key_Minus: viewer.zoomTo(viewer.zoom / 1.5); break
            case Qt.Key_0: viewer.fit(); break
            case Qt.Key_R: viewer.turn = (viewer.turn + ((event.modifiers & Qt.ShiftModifier) ? 270 : 90)) % 360; break
            case Qt.Key_Space: case Qt.Key_MediaTogglePlayPause:
                if (viewer.many) viewer.slideshow = !viewer.slideshow
                break
            case Qt.Key_F: if (!ctrl) viewer.toggleFull(); else handled = false; break
            case Qt.Key_Escape:
                if (viewer.full) viewer.showNormal()
                else if (viewer.slideshow) viewer.slideshow = false
                else handled = false
                break
            case Qt.Key_Delete: if (playerController.photoHistoryId > 0) deleteDialog.open(); break
            // Show the hidden controls first, then let Tab move focus into them.
            case Qt.Key_Tab: case Qt.Key_Backtab: viewer.showControls(); handled = false; break
            default: handled = false
            }
            if (handled) {
                viewer.showControls()
                event.accepted = true
            }
        }
    }

    AppDialog {
        id: deleteDialog
        parent: stage
        title: "Move this picture to the Recycle Bin?"
        width: Math.min(440, stage.width - 2 * Theme.spaceXl)
        standardButtons: Dialog.Ok | Dialog.Cancel
        defaultButton: Dialog.Ok
        onOpened: viewer.slideshow = false
        onAccepted: libraryController.deleteFiles([playerController.photoHistoryId])
        onClosed: stage.forceActiveFocus()
        Text {
            textFormat: Text.PlainText
            width: parent.width
            text: "It goes to the Recycle Bin, where you can restore it, and leaves the library."
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.text
            wrapMode: Text.WordWrap
        }
    }

    // The control-bar buttons; a click keeps the controls shown.
    component ViewerButton: OverlayButton { onClicked: viewer.showControls() }
}
