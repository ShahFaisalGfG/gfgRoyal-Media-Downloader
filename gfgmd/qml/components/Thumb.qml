// qmllint disable unqualified
import QtQuick

// A video thumbnail from the disk cache, with an icon for its kind until (or unless) it loads.
Rectangle {
    id: thumb

    property string source: ""
    property string kind: "video"

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
        name: thumb.kind === "audio" ? "audio" : thumb.kind === "live" ? "live" : "video"
        size: Theme.iconLg
        color: Theme.textMuted
    }

    Image {
        id: image
        anchors.fill: parent
        anchors.margins: 1
        // revision re-runs this binding when a fetched thumbnail arrives in the cache.
        source: thumb.source ? thumbnails.localFor(thumb.source, thumbnails.revision) : ""
        // Portrait thumbnails (Shorts, TikToks, Reels) fit whole between bars instead of being cropped
        // to a strip from their middle.
        fillMode: image.implicitHeight > image.implicitWidth ? Image.PreserveAspectFit : Image.PreserveAspectCrop
        asynchronous: true
        smooth: true
        sourceSize.width: 192
        Accessible.ignored: true
    }
}
