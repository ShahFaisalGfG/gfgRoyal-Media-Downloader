# gfgRoyal Media Downloader v1.2.0 - Release Notes

**Released:** November 2026 · **Status:** Stable · **Platform:** Windows 10 version 1809 or later (64-bit); the `gfgmd` command line also runs on Linux

---

v1.2.0 adds search from the link box, parts of videos and one file per chapter, pictures from posts and picture sites with a built-in photo viewer, and Spotify playlists, albums, and songs. The in-app updater offers it to v1.0.0; your library, settings, and sign-ins stay.

---

## New

- **Search from the link box.** Type words instead of a link and **Search** finds them on YouTube, or YouTube Music's songs with Audio chosen. Results show with their thumbnails, channels, lengths, and views; download one, or tick several and **Download selected**. `gfgmd search WORDS` lists them with their links (`--music`, `--limit`, `--json`).
- **Part of a video.** Download options for one video offer **Part**: From and To times, or one of the video's chapters. The file name carries the times, so several parts sit side by side. **Exact cut** converts the part to the exact times (slower); Preferences > Downloads holds its default. `gfgmd` takes `--section START-END` and `--exact-cut`.
- **One file per chapter.** **Chapters** saves a chaptered video as one numbered file per chapter in a folder named after it, tagged with each chapter's title, its place, and the video's title as the album. An album video becomes its songs, each with its cover and lyrics. Preferences > Video and Audio hold its defaults; `gfgmd` takes `--split-chapters`.
- **Pictures.** A video download of an Instagram, X, Reddit, Pinterest, TikTok, Facebook, Tumblr, or Bluesky post saves its pictures too, and a post with pictures only saves them instead of failing. Links to pixiv, DeviantArt, Imgur, ArtStation, and Flickr, and direct links to pictures, save their pictures. They go to `Pictures\gfgRoyal Media Downloader`: one picture straight in, several in a folder named after the post. Download options preview a link's pictures, and **Save the pictures in posts** (Preferences > Downloads) or `gfgmd --no-photos` turns the pictures off for posts.
- **Photo viewer.** **View** on a picture opens it in its own window: fit, zoom with the wheel or + and -, drag to move, turn the view, slideshow, filmstrip, fullscreen, and Recycle Bin. GIFs and animated WebP pictures play.
- **Pictures in the Library.** Pictures show themselves as thumbnails, **Pictures** filters the list to them, and a post's pictures group in one row.
- **Spotify.** A Spotify playlist, album, or song link downloads each song from YouTube as audio with your Audio defaults. Songs are matched on their title, artists, and length (never more than 15 seconds off, and remixes, live versions, and covers lose out unless Spotify names them), saved as "Artist - Title" in a folder named after the list, and tagged with Spotify's title, artists, album, track number, and cover. Download options list the songs to pick from. A song with no good match is listed as skipped, by name.
- **Two more download tools.** gallery-dl (from Codeberg) saves pictures, and spotDL reads Spotify playlists past the 100 songs Spotify's page lists. Both install with the other tools and are checked against their published checksums. The app works without them. When either is missing (after updating from v1.0.0, for example), Downloads offers it with **Download tools**, the same card and button the first start uses, and Preferences > Tools says what each is for.

## Fixed

- A copy of the app installed with pip couldn't load its window style.
- After the tools updated, Preferences > Tools showed their old versions for several seconds while it started each tool again; it now shows the new versions at once.

## Install

- `gfgRoyal-Media-Downloader_1.2.0_user_installer.exe`: for your account, no administrator rights
- `gfgRoyal-Media-Downloader_1.2.0_system_installer.exe`: for every account on the PC
- `gfgRoyal-Media-Downloader_1.2.0_portable.exe`: one file, keeps its data beside itself
- `gfgRoyal-Media-Downloader_1.2.0_portable.7z`: the same, unpacked, with `gfgmd.exe`
- `gfgRoyal-Media-Downloader-Companion_1.0.0_chrome.zip`: the companion extension, unchanged since v1.0.0, loaded unpacked until its store listing

## Known limitations

- A profile on a post site (an Instagram or X account) saves its videos, not its pictures; picture sites' profiles save their pictures.
- Spotify artist and podcast links aren't supported. A playlist past 100 songs needs spotDL, which takes a few minutes to read it.
- The companion extension isn't in the Chrome Web Store yet; load it unpacked.
- Subscriptions are checked only while the app runs (in the tray, or after Start with Windows).
