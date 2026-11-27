// qmllint disable unqualified
import QtQuick

// The link box, which also searches. A paste button sits inside it while it is empty, the Download
// button once it holds a link (by its form: nothing is fetched to decide), and Search while it holds
// words. A link keeps only characters a link can hold: spaces, tabs, line breaks, invisible characters,
// and " < > \ ^ ` { | } are dropped as they are typed or pasted, and the caret stays where it was.
// Pasted text keeps only its links: the first in the box and the rest beside it as "+N more" (`links`
// hands over all of them); pasted text with no link in it becomes search words and searches at once.
// Words keep their spaces and lose only control and invisible characters. A bare
// "youtube.com/watch?v=..." gets its https:// in front. `linkReady` says a link has settled in the box,
// so it can be read ahead.
StyledTextField {
    id: field

    // Search for the words in the box (the Search button, or words pasted).
    signal searchRequested()
    // The Download button inside the box was pressed.
    signal downloadRequested()
    // The box has held this link for a moment (a paste, or typing that stopped).
    signal linkReady(string url)

    property bool downloadEnabled: true
    property string downloadToolTip: ""
    // The box holds a link by its form.
    readonly property bool valid: field.links.length > 0 && appController.validLink(field.links[0])
    // The box holds words to search for rather than a link.
    readonly property bool searching: field.text.trim().length > 0 && !field.valid && field.extraLinks.length === 0

    // The other links of a paste, downloaded with the one in the box.
    property var extraLinks: []
    // The box's link (with https:// in front when typed bare), then the rest of a paste.
    readonly property var links: field.text.length > 0 ? [field._asLink(field.text) || field.text].concat(field.extraLinks) : []
    // The box's text before the latest change, put back when a paste held no link.
    property string _previous: ""

    // Put text in the box: its links (the first in the box, the rest as extras), or, with no link in
    // it, its words, which are searched for at once.
    function setLinks(text) {
        var words = String(text).split(/\s+/).map(word => field._clean(word)).filter(word => word.length > 0)
        var found = words.map(word => field._asLink(word)).filter(word => word.length > 0)
        field.extraLinks = found.slice(1)
        settle.stop()
        if (found.length === 0) {
            field.text = field._cleanWords(String(text)).split(/ +/).filter(word => word.length > 0).join(" ").slice(0, 200)
            field.input.cursorPosition = field.text.length
            if (field.text.length > 0) field.searchRequested()
            return true
        }
        field.text = found[0]
        field.input.cursorPosition = field.text.length
        if (field.valid) field.linkReady(field.links[0])
        return true
    }
    // A word as a link: as it is with http(s)://, with https:// in front when it looks like a site's
    // address and path ("youtu.be/abc"), else "".
    function _asLink(word) {
        if (/^https?:\/\//i.test(word)) return word
        if (/^[a-z0-9-]+(\.[a-z0-9-]+)+\/\S/i.test(word)) return "https://" + word
        return ""
    }
    function pasteClipboard() {
        field.setLinks(appController.clipboardText())
        field.input.forceActiveFocus()
    }
    function clear() {
        field.extraLinks = []
        field.text = ""
    }

    function _clean(text) {
        return text.replace(/[\s\u0000-\u001f\u007f-\u009f\u00ad\u200b-\u200f\u2028-\u202e\u2060-\u2064\ufeff"<>\\^`{|}]/g, "")
    }
    // Search words keep their spaces; tabs and line breaks become spaces, invisible characters go.
    function _cleanWords(text) {
        return text.replace(/[\u0000-\u001f\u007f-\u009f]/g, " ").replace(/[\u00ad\u200b-\u200f\u2028-\u202e\u2060-\u2064\ufeff]/g, "")
    }
    // Text that is, or holds, a link: "https://...", "www....", or a site's address and path.
    function _linkLike(text) {
        return /(^|\s)(https?:\/\/|www\.|[a-z0-9-]+(\.[a-z0-9-]+)+\/)/i.test(text)
    }

    // A pasted link settles at once; typing waits until the keys stop.
    Timer {
        id: settle
        interval: 400
        onTriggered: if (field.valid) field.linkReady(field.links[0])
    }

    Connections {
        target: field.input
        function onTextChanged() {
            settle.restart()
            var text = field.input.text
            if (text.length === 0) {
                field.extraLinks = []
                field._previous = ""
                return
            }
            if (!field._linkLike(text)) {
                // Search words, as typed: spaces stay.
                var words = field._cleanWords(text)
                if (words !== text) {
                    var at = field._cleanWords(text.slice(0, field.input.cursorPosition)).length
                    field.input.text = words
                    field.input.cursorPosition = at
                }
                field._previous = field.input.text
                return
            }
            var clean = field._clean(text)
            if (clean === text) {
                field._previous = text
                return
            }
            // Text with spaces or line breaks and a link in it arrived at once (a paste): keep only its
            // links, never glue its words into one.
            if (/\S\s+\S/.test(text.trim())) {
                field.setLinks(text)
                field._previous = field.input.text
                return
            }
            var caret = field._clean(text.slice(0, field.input.cursorPosition)).length
            field.input.text = clean
            field.input.cursorPosition = caret
            field._previous = clean
        }
    }

    trailing: [
        AppButton {
            visible: field.text.length === 0
            kind: "ghost"
            compact: true
            iconName: "paste"
            toolTipText: "Paste the copied link (Ctrl+V)"
            onClicked: field.pasteClipboard()
        },
        AppButton {
            visible: field.extraLinks.length > 0
            kind: "ghost"
            compact: true
            text: "+" + field.extraLinks.length + " more"
            toolTipText: field.extraLinks.length + " more link" + (field.extraLinks.length === 1 ? "" : "s")
                + " pasted, downloaded along with this one. Click to leave "
                + (field.extraLinks.length === 1 ? "it" : "them") + " out.\n" + field.extraLinks.slice(0, 5).join("\n")
                + (field.extraLinks.length > 5 ? "\n..." : "")
            onClicked: field.extraLinks = []
        },
        AppButton {
            visible: field.valid
            enabled: field.downloadEnabled
            kind: "primary"
            compact: true
            text: "Download"
            iconName: "download"
            toolTipText: field.downloadToolTip
            onClicked: field.downloadRequested()
        },
        AppButton {
            visible: field.searching
            enabled: field.downloadEnabled
            kind: "primary"
            compact: true
            text: "Search"
            iconName: "search"
            toolTipText: field.downloadToolTip
            onClicked: field.searchRequested()
        }
    ]
}
