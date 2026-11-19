// qmllint disable unqualified
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

import "../components"

// Sign in to sites so their private, members-only, and age-restricted videos (and Instagram or
// Facebook posts) can download. Sign-ins stay encrypted on this PC; each download receives only
// its own site's cookies, and only for as long as it runs.
//
// Sign in opens the site in the user's default browser (in a window of its own, on a profile of its
// own); Done closes that window and saves the sign-in. Other ways to sign in are under "Other ways".
Item {
    id: page

    // A link from a site's own lists (YouTube's Watch later, Liked videos, playlists) to read.
    signal openLink(string url)

    function otherWays(siteKey, label) {
        methodDialog.siteKey = siteKey
        methodDialog.title = "Sign in to " + label
        methodDialog.open()
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spaceXl
        spacing: Theme.spaceLg

        Text {
            Layout.fillWidth: true
            text: "Signing in lets the app download what a site shows only to your account. Your sign-in is "
                + "saved encrypted for your Windows account on this PC, never sent anywhere else, and each "
                + "download gets only its own site's cookies. Sign out here at any time."
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.textMuted
            wrapMode: Text.WordWrap
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm
            StyledTextField {
                id: otherSite
                Layout.fillWidth: true
                placeholderText: "Another site: paste a link or type its address (example.com)"
                onAccepted: addButton.clicked()
            }
            AppButton {
                id: addButton
                text: "Add site"
                iconName: "add"
                toolTipText: "Add a site that isn't listed"
                onClicked: {
                    var key = signInsController.addSite(otherSite.text)
                    if (key.length > 0) otherSite.text = ""
                }
            }
        }

        ListView {
            id: view
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: signInsController.model
            spacing: 2
            boundsBehavior: Flickable.StopAtBounds
            keyNavigationEnabled: true
            activeFocusOnTab: true
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Accessible.role: Accessible.List
            Accessible.name: "Sites"

            delegate: Rectangle {
                id: site
                required property int index
                required property string siteKey
                required property string label
                required property string status
                required property string statusText
                required property string methodText
                required property string detail
                required property bool busy
                required property bool canRefresh
                required property bool windowOpen
                required property var library

                width: view.width
                height: siteColumn.implicitHeight + 2 * Theme.spaceSm
                radius: Theme.radius
                color: siteHover.hovered || ListView.isCurrentItem ? Theme.surfaceHover : "transparent"
                Accessible.role: Accessible.ListItem
                Accessible.name: site.label + ", " + site.statusText
                HoverHandler { id: siteHover }

                ColumnLayout {
                    id: siteColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: Theme.spaceMd
                    anchors.rightMargin: Theme.spaceSm
                    spacing: Theme.spaceXs

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.minimumHeight: 48
                        spacing: Theme.spaceMd

                        Icon {
                            name: site.status === "ok" ? "completed" : site.status === "expired" ? "warning" : "account"
                            size: Theme.iconLg
                            color: site.status === "ok" ? Theme.success : site.status === "expired" ? Theme.warning : Theme.textMuted
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 3
                            Text {
                                text: site.label
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontBody
                                font.weight: Font.DemiBold
                                color: Theme.text
                            }
                            Text {
                                Layout.fillWidth: true
                                text: [site.statusText, site.methodText, site.detail].filter(p => p.length > 0).join("  ·  ")
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontCaption
                                color: site.status === "expired" ? Theme.warning : Theme.textMuted
                                elide: Text.ElideRight
                            }
                        }
                        BusyIndicator { visible: site.busy; running: visible; implicitWidth: 24; implicitHeight: 24 }
                        AppButton {
                            visible: site.canRefresh && !site.busy
                            kind: "ghost"
                            text: "Refresh"
                            iconName: "refresh"
                            toolTipText: "Read the sign-in from its browser profile again (no window opens)"
                            onClicked: signInsController.refresh(site.siteKey)
                        }
                        AppButton {
                            visible: site.status !== "none" && !site.busy && !site.windowOpen
                            kind: "ghost"
                            text: "Sign out"
                            iconName: "close"
                            toolTipText: "Delete this sign-in from this PC"
                            onClicked: signInsController.signOut(site.siteKey)
                        }
                        AppButton {
                            visible: site.windowOpen
                            kind: "ghost"
                            text: "Cancel"
                            toolTipText: "Close the sign-in window without saving"
                            onClicked: signInsController.cancelBrowserWindow(site.siteKey)
                        }
                        AppButton {
                            visible: site.windowOpen
                            kind: "primary"
                            text: "Done"
                            iconName: "check"
                            toolTipText: "Signed in? The app closes the window and saves the sign-in"
                            onClicked: signInsController.finishBrowserWindow(site.siteKey)
                        }
                        AppButton {
                            visible: !site.busy && !site.windowOpen
                            kind: "ghost"
                            compact: true
                            iconName: "more"
                            toolTipText: "Other ways to sign in (another browser, the companion extension, Firefox, a cookies file)"
                            onClicked: page.otherWays(site.siteKey, site.label)
                        }
                        AppButton {
                            visible: !site.busy && !site.windowOpen
                            kind: site.status === "ok" ? "secondary" : "primary"
                            text: site.status === "ok" ? "Sign in again" : "Sign in"
                            iconName: "key"
                            enabled: signInsController.browsers.length > 0
                            toolTipText: signInsController.browsers.length > 0
                                ? "Opens " + site.label + " in " + signInsController.browsers[0].label.replace(" (your default)", "")
                                  + ". Sign in there, then click Done here."
                                : "No supported browser was found; use Other ways"
                            onClicked: signInsController.openBrowserWindow(site.siteKey, "")
                        }
                    }

                    // The signed-in account's own lists, ready to download.
                    Flow {
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.iconLg + Theme.spaceMd
                        Layout.bottomMargin: Theme.spaceXs
                        visible: site.library.length > 0
                        spacing: Theme.spaceSm
                        Repeater {
                            model: site.library
                            delegate: AppButton {
                                required property var modelData
                                compact: true
                                text: modelData.label
                                iconName: "list"
                                toolTipText: "Open " + modelData.label + " to choose what to download"
                                onClicked: page.openLink(modelData.url)
                            }
                        }
                    }
                }
            }
        }
    }

    AppDialog {
        id: methodDialog
        property string siteKey: ""
        property string method: "browser"
        standardButtons: Dialog.Ok | Dialog.Cancel
        defaultButton: Dialog.Ok
        width: Math.min(page.width - 2 * Theme.spaceXl, 560)
        onOpened: {
            methodDialog.method = signInsController.browsers.length > 0 ? "browser" : "extension"
            browserBox.currentIndex = 0
        }
        onAccepted: {
            if (methodDialog.method === "browser") signInsController.openBrowserWindow(methodDialog.siteKey, browserBox.currentValue)
            else if (methodDialog.method === "firefox") signInsController.useFirefox(methodDialog.siteKey, firefoxProfile.text)
            else if (methodDialog.method === "file") cookiesDialog.open()
        }

        ColumnLayout {
            width: parent.width
            spacing: Theme.spaceMd

            RadioButton {
                checked: methodDialog.method === "browser"
                enabled: signInsController.browsers.length > 0
                text: "In a browser window (recommended)"
                font.family: Theme.fontFamily
                onClicked: methodDialog.method = "browser"
            }
            RowLayout {
                Layout.leftMargin: Theme.spaceXl
                Layout.fillWidth: true
                visible: methodDialog.method === "browser"
                StyledComboBox {
                    id: browserBox
                    Layout.preferredWidth: 220
                    model: signInsController.browsers
                    accessibleName: "Browser"
                }
                Text {
                    Layout.fillWidth: true
                    text: "A separate window opens on the site's sign-in page. Sign in, then click Done here."
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontCaption
                    color: Theme.textMuted
                    wrapMode: Text.WordWrap
                }
            }
            RadioButton {
                checked: methodDialog.method === "extension"
                text: "From your browser with the companion extension"
                font.family: Theme.fontFamily
                onClicked: methodDialog.method = "extension"
            }
            Text {
                Layout.leftMargin: Theme.spaceXl
                Layout.fillWidth: true
                visible: methodDialog.method === "extension"
                text: "Open the site signed in, click the extension's button, and choose Sign this site in. "
                    + "Works in Chrome, Edge, Opera, and Brave; for YouTube, a private window keeps the sign-in "
                    + "from changing while you browse."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.textMuted
                wrapMode: Text.WordWrap
            }
            RadioButton {
                checked: methodDialog.method === "firefox"
                text: "Use Firefox's sign-in on each download"
                font.family: Theme.fontFamily
                onClicked: methodDialog.method = "firefox"
            }
            StyledTextField {
                id: firefoxProfile
                Layout.leftMargin: Theme.spaceXl
                Layout.fillWidth: true
                visible: methodDialog.method === "firefox"
                placeholderText: "Firefox profile name (leave empty for the default)"
            }
            RadioButton {
                checked: methodDialog.method === "file"
                text: "Import a cookies.txt file"
                font.family: Theme.fontFamily
                onClicked: methodDialog.method = "file"
            }
            Text {
                Layout.leftMargin: Theme.spaceXl
                Layout.fillWidth: true
                visible: methodDialog.method === "file"
                text: "A Netscape-format file exported from your browser. Only this site's cookies are kept, "
                    + "encrypted; the app then offers to move the original file to the Recycle Bin."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.textMuted
                wrapMode: Text.WordWrap
            }
        }
    }

    FileDialog {
        id: cookiesDialog
        title: "Choose a cookies.txt file"
        nameFilters: ["Cookies files (*.txt)", "All files (*)"]
        onAccepted: signInsController.importFile(methodDialog.siteKey, appController.localPath(selectedFile.toString()))
    }

    Connections {
        target: signInsController
        function onOfferDeleteOriginal(path) {
            deleteOriginal.path = path
            deleteOriginal.open()
        }
    }

    AppDialog {
        id: deleteOriginal
        property string path: ""
        title: "Move the cookies file to the Recycle Bin?"
        standardButtons: Dialog.Yes | Dialog.No
        defaultButton: Dialog.Yes
        width: 440
        onAccepted: signInsController.deleteOriginal(deleteOriginal.path)
        Text {
            width: parent.width
            text: "The app keeps its own encrypted copy. The original file gives access to your account to "
                + "anyone who reads it."
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.text
            wrapMode: Text.WordWrap
        }
    }
}
