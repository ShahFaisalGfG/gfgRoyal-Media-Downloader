# Privacy Policy

gfgRoyal Media Downloader has no accounts, no telemetry, and no ads. It never sends what you download, your library, your settings, or your sign-ins to the developer or to anyone else. This page lists every place the app connects to.

## Connections you ask for

- **The sites you download from, play from, subscribe to, or sign in to.** yt-dlp reads and downloads the links you give the app, and the app fetches their thumbnails. A link pasted into the link box is read as soon as it is pasted, and a YouTube link's title and thumbnail come first from YouTube's own oEmbed page (youtube.com/oembed), which is sent only that link. Subscriptions check the channels and playlists you added, as often as you set.
- **A site's sign-in page**, opened in a browser window of its own when you click Sign in. A YouTube sign-in is checked once by opening your Watch later list.
- **YouTube's search**, when you type words in the link box (YouTube Music's song search with Audio chosen). The words go to YouTube, as a search on its own site would send them.
- **Spotify and YouTube, for a Spotify link.** The app reads the playlist's, album's, or song's public embed page (open.spotify.com/embed) and its cover from Spotify's picture servers, then searches YouTube for each song by its artist and title and downloads the matches from YouTube. For a playlist longer than 100 songs, spotDL reads the whole list from Spotify's web player. Spotify is sent only the link; no Spotify account is used.
- **Picture sites** (Instagram, X, Reddit, Pinterest, pixiv, Imgur, Flickr, and others), when you download a post's pictures or a picture link: gallery-dl reads them from the site, as yt-dlp does videos.
- **The download tools' releases** when you choose to install or update them from Preferences > Tools: yt-dlp, FFmpeg, Deno, and spotDL from GitHub, and gallery-dl from Codeberg (codeberg.org), each checked against its published checksum.

## Connections the app makes on its own

Each of these is on unless you turned it off during installation, and each can be turned off at any time in Preferences.

- **App updates (GitHub), once a day.** The app asks GitHub whether a newer version exists; the request carries only the app's name and version. Turn it off in Preferences > Updates and logs.
- **Download tool updates (GitHub and Codeberg), once a day.** The app checks the yt-dlp, FFmpeg, Deno, gallery-dl, and spotDL releases and installs newer versions, checking every file against its published checksum. On a metered connection it waits until you're off it, unless Preferences > Updates and logs allows updates there. Turn it off in Preferences > Tools.
- **Lyrics (LRCLIB, lrclib.net).** When an audio download has no lyrics from its own site, the app sends the song's title, artist, album, and length to LRCLIB, a free lyrics service, to find them. Turn it off in Preferences > Audio.

These services have their own privacy policies: [GitHub's privacy statement](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement), [Codeberg's privacy policy](https://codeberg.org/codeberg/org/src/branch/main/PrivacyPolicy.md), [Spotify's privacy policy](https://www.spotify.com/legal/privacy-policy/), and [LRCLIB](https://lrclib.net).

## What stays on your PC

- Your downloads, library, settings, and subscriptions.
- Your sign-ins, encrypted for your Windows account. A download that needs one gets a copy for that run only.
- Logs, which are off by default, stay on your PC, and never contain your sign-ins.

## The companion browser extension

The extension talks only to the app on this PC. It sends a site's cookies to the app only when you choose **Sign this site in to the app**, and it gives back its permission to read that site's cookies right after.

## Contact

Questions about privacy: open an issue at https://github.com/ShahFaisalGfG/gfgRoyal-Media-Downloader/issues or email shahfaisalgfg@gmail.com.
