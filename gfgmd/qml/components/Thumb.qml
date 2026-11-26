// qmllint disable unqualified
import QtQuick

// A media thumbnail from the disk cache, with an icon for its kind until (or unless) it loads.
// Songs show a square cover in the middle, as music players show artwork, and videos fill the
// frame; a badge in the corner names the kind ("video", "audio", "live", or "playlist") and, given
// `label`, the format ("MP3", "MP4"), so they tell apart at a glance in any list.
Rectangle {
    id: thumb

    property string source: ""
    property string kind: "video"
    property string label: ""
    readonly property bool _audio: thumb.kind === "audio"
    readonly property string _kindIcon: thumb._audio ? "audio" : thumb.kind === "live" ? "live"
                                      : thumb.kind === "playlist" ? "list" : "video"

    implicitWidth: 96
    implicitHeight: 54
    radius: Theme.radius
    color: Theme.surfaceAlt
    border.width: 1
    border.color: Theme.border
    clip: true

    Icon {
        anchors.centerIn: parent
        visible: image.status !== Image.Ready
        name: thumb._kindIcon
        size: Theme.iconLg
        color: Theme.textMuted
    }

    Image {
        id: image
        anchors.centerIn: parent
        width: thumb._audio ? thumb.height - 2 : thumb.width - 2
        height: thumb.height - 2
        // revision re-runs this binding when a fetched thumbnail arrives in the cache.
        source: thumb.source ? thumbnails.localFor(thumb.source, thumbnails.revision) : ""
        // A song's cover is the thumbnail's middle square, as its file's cover is. Portrait video
        // thumbnails (Shorts, TikToks, Reels) fit whole between bars instead of being cut to a strip.
        fillMode: !thumb._audio && image.implicitHeight > image.implicitWidth ? Image.PreserveAspectFit
                                                                              : Image.PreserveAspectCrop
        asynchronous: true
        smooth: true
        sourceSize.width: 192
        Accessible.ignored: true
    }

    // The kind (and format) badge; dark in both themes, since it sits on a picture.
    Rectangle {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 3
        width: badge.implicitWidth + 8
        height: 16
        radius: Theme.radius
        color: Theme.mediaBadge
        Accessible.ignored: true

        Row {
            id: badge
            anchors.centerIn: parent
            spacing: 3

            Icon {
                id: badgeIcon
                anchors.verticalCenter: parent.verticalCenter
                name: thumb._kindIcon
                size: Theme.iconXs
                color: Theme.mediaBadgeText
            }
            Text {
                textFormat: Text.PlainText
                anchors.verticalCenter: parent.verticalCenter
                // Never wider than the thumbnail leaves room for (less the badge's 3 px margins and
                // 8 px padding, and the icon): a long label is cut short instead of spilling out.
                width: Math.min(implicitWidth, thumb.width - 14 - badgeIcon.width - badge.spacing)
                visible: thumb.label.length > 0
                text: thumb.label
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                font.weight: Font.DemiBold
                color: Theme.mediaBadgeText
            }
        }
    }
}
