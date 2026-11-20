// qmllint disable unqualified
import QtQuick

// The link box. A paste button sits inside it while it is empty. Only characters a link can hold
// get in: spaces, tabs, line breaks, invisible characters, and " < > \ ^ ` { | } are dropped as
// they are typed or pasted, and the caret stays where it was. Pasting several links at once keeps
// the first in the box and the rest beside it as "+N more"; `links` hands over all of them.
StyledTextField {
    id: field

    // The other links of a paste, downloaded with the one in the box.
    property var extraLinks: []
    readonly property var links: field.text.length > 0 ? [field.text].concat(field.extraLinks) : []

    // Put text in the box: its links (the first in the box, the rest as extras), else the text
    // itself without the characters a link can't hold.
    function setLinks(text) {
        var words = String(text).split(/\s+/).map(word => field._clean(word)).filter(word => word.length > 0)
        var found = words.filter(word => /^https?:\/\//i.test(word))
        field.extraLinks = found.slice(1)
        field.text = found.length > 0 ? found[0] : words.join("")
        field.input.cursorPosition = field.text.length
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

    Connections {
        target: field.input
        function onTextChanged() {
            var text = field.input.text
            if (text.length === 0) {
                field.extraLinks = []
                return
            }
            var clean = field._clean(text)
            if (clean === text) return
            // Several links arrived at once (a paste): keep them apart instead of gluing them together.
            if (text.split(/\s+/).filter(word => /^https?:\/\//i.test(word)).length > 1) {
                field.setLinks(text)
                return
            }
            var caret = field._clean(text.slice(0, field.input.cursorPosition)).length
            field.input.text = clean
            field.input.cursorPosition = caret
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
        }
    ]
}
