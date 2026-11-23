<div align="center">

<img src="gfgmd/assets/icons/Square150x150Logo.scale-100.png" alt="gfgRoyal Media Downloader" width="96" />

# gfgRoyal Media Downloader

**Download and play videos, music, Shorts, playlists, channels, and live streams from YouTube, TikTok, Instagram, Facebook, X, and the other sites yt-dlp supports: a desktop app with a queue, built-in players, synced lyrics, subscriptions, website sign-ins, and a command-line tool, free and open source.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB.svg?logo=python&logoColor=white)](pyproject.toml)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D4.svg)](#download--install)
[![Tests](https://github.com/ShahFaisalGfG/gfgRoyal-Media-Downloader/actions/workflows/tests.yml/badge.svg)](.github/workflows/tests.yml)

</div>

---

gfgRoyal Media Downloader saves a single video, a whole playlist, a channel, a Short or Reel, or a live stream as clean, quality-labeled files such as `Episode 001 (1080p).mp4`, and music as MP3 (320 kbps by default) or another format with its cover art and synced lyrics. Paste a link and press Download, or the arrow on the Download button to pick the quality, audio tracks, subtitles, and the exact videos you want. Play what you downloaded in the built-in video and music players. Downloads resume after a dropped connection, a crash, or a restart, and the app keeps its own copies of yt-dlp, FFmpeg, and Deno up to date so site changes don't break it.

> *Paste once. Come back to a finished playlist.*

It grew out of YouTube Video Downloader, an earlier command-line script. Version 1.0.0 is the first release of the desktop app for video and music, and the script lives on as the `gfgmd` command line, with the same options.

---

## Table of Contents

- [Who Is This For?](#who-is-this-for)
- [Features](#features)
- [Download & Install](#download--install)
- [Quick Start](#quick-start)
- [Video and Audio Formats](#video-and-audio-formats)
- [Lyrics](#lyrics)
- [Extract Audio](#extract-audio)
- [Built-in Players](#built-in-players)
- [Shorts, Reels, and Other Sites](#shorts-reels-and-other-sites)
- [Signing In to Sites](#signing-in-to-sites)
- [Subscriptions](#subscriptions)
- [Scheduling and When-Done](#scheduling-and-when-done)
- [Live Streams](#live-streams)
- [Companion Browser Extension](#companion-browser-extension)
- [Command Line](#command-line)
- [Where Files Go](#where-files-go)
- [Quality and Speed](#quality-and-speed)
- [The Download Tools](#the-download-tools)
- [Privacy and Security](#privacy-and-security)
- [Code Signing Policy](#code-signing-policy)
- [Troubleshooting](#troubleshooting)
- [Building from Source](#building-from-source)
- [Roadmap](#roadmap)
- [Changelog](#changelog)
- [Responsible Use](#responsible-use)
- [License & Credits](#license--credits)

---

## Who Is This For?

- **Learners** saving course playlists to watch offline
- **Travelers and commuters** with slow or unreliable connections
- **Creators and archivists** keeping copies of their own uploads and channels
- **Anyone** who wants files that play everywhere, named by title and quality

---

## Features

- 📚 **Every kind of link**: YouTube videos, Shorts, playlists, and channels (Videos, Shorts, and Live tabs); TikToks, Instagram and Facebook Reels and posts, X posts, Snapchat Spotlight, Pinterest, and Reddit; and the other sites yt-dlp supports, such as Vimeo, Twitch, Dailymotion, and SoundCloud
- 🎯 **Video your way**: best quality up to 4K or any limit, MP4, MKV, or WebM, files that play everywhere or the best picture the site has, and the original audio track or dubbed languages too
- 🎵 **Music your way**: MP3 at 320 kbps by default, or 64 to 256 kbps, M4A, Opus, OGG, lossless FLAC or WAV, or the site's own stream; the thumbnail becomes a square album cover, and artist and title go in the tags
- 🎤 **Synced lyrics**: songs get a timed `.lrc` file from the site's captions, or from LRCLIB when the length matches, and plain lyrics in the file's tags
- ▶️ **Built-in players**: a video player with subtitles, audio tracks, speed, and fullscreen, and a music player with a queue, shuffle, repeat, cover art, and lyrics that follow the song
- 🧾 **Pick the videos**: read a playlist or channel first, then filter, check ranges, or take only the videos you don't have yet
- 💬 **Subtitles and extras**: written or automatic subtitles in the languages you pick, embedded, as SRT or WebVTT files, or both; embedded thumbnail, details, and chapters; SponsorBlock marks or cuts sponsor segments
- 🗂️ **A full queue**: several downloads at once, per-site limits, pause, resume, retry, reorder, and progress on the taskbar; a playlist, channel, or subscription lists every video under it, each saved, waiting, or downloading
- ⏯️ **Resumable**: partial files continue, finished videos are skipped through per-playlist archives, and interrupted downloads resume when the app starts again
- 🔁 **Knows when to retry**: dropped connections retry with growing waits; a video whose server stops answering waits while the rest of its playlist downloads; a signed-in playlist's video that fails with the sign-in is downloaded once more without it; private, removed, or region-locked videos are skipped instead of retried forever; a sign-in request or a full disk stops and tells you why
- 🔑 **Website sign-ins**: one click opens the site in your own browser; sign in and click Done, and your private playlists, Watch later, Liked videos, and members-only or age-restricted videos download; sign-ins stay encrypted on your PC
- 🔔 **Subscriptions**: watch channels and playlists and download new uploads on a schedule, without downloading anything twice
- 🕑 **Scheduling**: start the queue at a set time, limit the speed by time of day, and sleep or shut down the PC when everything is done
- 🔴 **Live streams**: record from the start, or wait for a scheduled stream or premiere and record it when it begins
- 🧩 **Companion extension**: send the page you are watching to the app, or sign a site in, from Chrome, Edge, Opera, Brave, or Vivaldi
- 🗄️ **Library**: every finished download, searchable, with each playlist and channel grouped in its own order, and Play, Play all, show in folder, extract audio, download again, and Recycle Bin
- ⌨️ **Command line**: `gfgmd` keeps the original script's options and exit codes for scripts and scheduled tasks
- 🎨 **Built for everyday use**: light and dark themes, keyboard shortcuts, tooltips everywhere, tray icon, notifications, and in-app updates

---

## Download & Install

Get the latest release from the [Releases page](https://github.com/ShahFaisalGfG/gfgRoyal-Media-Downloader/releases/latest):

| File | Use it when |
|---|---|
| `gfgRoyal-Media-Downloader_<version>_user_installer.exe` | You want it for your account only; no administrator rights needed |
| `gfgRoyal-Media-Downloader_<version>_system_installer.exe` | You want it for every account on the PC |
| `gfgRoyal-Media-Downloader_<version>_portable.exe` | You want one file that runs from anywhere and keeps its data beside itself |
| `gfgRoyal-Media-Downloader_<version>_portable.7z` | The same, unpacked, with `gfgmd.exe` included |
| `gfgRoyal-Media-Downloader-Companion_<version>_chrome.zip` | The companion browser extension (see [below](#companion-browser-extension)) |

The Windows files are signed as the [Code signing policy](#code-signing-policy) describes, and the installers show the [privacy policy](PRIVACY.md) before they install.

Windows 10 version 1809 or later, 64-bit. On first start the app offers to download yt-dlp, FFmpeg, and Deno (about 280 MB) from their official releases; or choose **Use the installed tools** if you installed them yourself with winget.

### Updating

The app checks GitHub once a day and installs updates when you quit, after checking the release's signature and checksums. Preferences > Updates and logs turns either step off. Your downloads, library, sign-ins, and settings stay.

---

## Quick Start

1. Copy a link from your browser.
2. Press **Ctrl+V** in the app (or the paste button inside the empty link box), choose a preset, and press **Download**.
3. To choose formats and videos first, press the arrow on the right of **Download** (or Ctrl+Shift+O) instead; press it again to close the choices.

Drag links from the browser onto the window to queue them, or drop a `.txt` file with one link per line. Turn on **Offer copied links** in Preferences and the app offers to download each link you copy.

**Downloads** lists what is downloading, waiting, paused, or failed, and what finished since you opened the app; the **Library** keeps every finished file.

A playlist, channel, or several new uploads from a subscription make one download that lists every video under it, numbered, as soon as the site names them: **Saved**, **Downloading** with its size, speed, and time left, **Waiting**, **Downloaded before**, **Skipped** with the reason, or **Waiting for its server**. Its button (**8 videos**, **8 songs**) shows or hides the list, and each song lands in the Library the moment it is saved. When a video's download stops moving for a minute and a half (its server stopped answering), it waits while the rest of the list downloads, then tries again with fresh links; the playlist's progress counts what is saved and never jumps back. **Clear finished** above the list tidies it at any time, and finished downloads leave it on their own when you quit the app (Preferences > Downloads can keep them). Failed and unfinished downloads stay, to be tried again or resumed.

Songs show a square cover and videos a wide thumbnail, each with a badge naming the type (**♪ MP3**, **▶ MP4**). To act on several at once, select them with the round box on their thumbnails (it appears on hover or on the row the keyboard is on), or Ctrl+click and Shift+click them; a bar above the list then offers Pause, Resume, Try again, and Remove in Downloads, and Play, Extract audio, Remove, and Recycle Bin in the Library. **Select all** there takes every file the Library's search and filters show.

| Shortcut | Action |
|---|---|
| Ctrl+V | Paste the copied link |
| Enter | Download with the chosen preset |
| Ctrl+Shift+O | Open the download options for the link |
| Esc / Ctrl+Enter | In the download options: close them / add the download |
| Ctrl+L | Go to the link box |
| Space | Pause or resume the selected download |
| Delete | Remove the selected download from the list (asks first when it is unfinished or has saved files) |
| Ctrl+click, Shift+click | Select several downloads or library files, or a range of them |
| Ctrl+A / Ctrl+Space / Esc | Select every row / select the current row / clear the selection |
| Menu key or Shift+F10 | Open the current row's menu (Downloads, Library, Subscriptions) |
| Enter | Play the current file or group (Library); check now (Subscriptions); sign in (Sign-ins) |
| Right / Left | Show or hide a playlist's videos (Downloads) or a group's files (Library) |
| Ctrl+Shift+P | Pause or resume every download |
| Ctrl+1 to Ctrl+4 | Downloads, Library, Subscriptions, Sign-ins |
| Ctrl+, | Preferences |
| F5 | Check subscriptions now (on Subscriptions) |
| F1 | About |
| Ctrl+Q | Quit (closing the window keeps the app in the tray; asks first while downloading) |

---

## Video and Audio Formats

Presets next to the link box cover the usual choices (video in the best quality offered as MP4 or MKV, MP3 320 kbps, M4A, FLAC); the arrow on the **Download** button shows every choice for one link, and Preferences sets the starting values.

| Video | Choices |
|---|---|
| Quality | Best available, 2160p, 1440p, 1080p, 720p, 480p, 360p (measured on the shorter side, so portrait Shorts fit too) |
| File type | MP4 (plays everywhere), MKV (keeps everything), WebM (for web browsers) |
| Compatibility | Plays everywhere (recommended), Balanced (highest resolution first), Best quality (not for older devices) |
| Audio tracks | The original language only, or dubbed languages too as extra tracks in one MP4 or MKV file; the download options list the languages a video has |
| Subtitles | None, embedded, separate SRT or WebVTT files, or both; pick the languages, and optionally the site's automatic captions |

| Audio | Choices |
|---|---|
| Format | MP3 (default), M4A (Apple devices), Opus, OGG, FLAC and WAV (full quality, larger files), or Original (the site's own sound, as it sends it) |
| Quality | 320 kbps (default), 256, 192, 160, 128, 96, or 64 kbps; FLAC, WAV, and Original have none. Higher numbers sound better and make bigger files; above 256 the sound can't get better than the site's. M4A and Opus keep the site's sound as it is when they can |
| Cover | The video's thumbnail, cropped square like an album cover or kept in its shape; WAV gets it as a `.jpg` beside the file |
| Lyrics | A timed `.lrc` file and plain lyrics in the tags (see [Lyrics](#lyrics)) |

---

## Lyrics

Audio downloads save the song's lyrics as `<song>.lrc` beside the file, timed line by line, which the built-in music player and most music players show as the song plays. The site's own captions come first, in the song's language: they were timed against this very recording. When a song has none, the app asks [LRCLIB](https://lrclib.net), a free and open lyrics database, by artist, title, album, and length, and uses its timed lyrics only when the track length matches the file within two seconds, so the lines land where they are sung. Plain lyrics also go in the file's tags (MP3, M4A, and FLAC). Turn lyrics or the LRCLIB lookup off in Preferences > Audio; the lookup sends only the song's title, artist, album, and length.

---

## Extract Audio

**Extract audio** in a finished download's menu (or a library video's) turns a video you already downloaded into a song, without downloading it again. It offers the audio download's choices, starting from Preferences: format and bitrate, the cover and its shape, the tags and chapters, and lyrics. The cover is the thumbnail the video holds, the artist and title are cleaned up as in audio downloads, and the lyrics come from the video's caption files, then LRCLIB. The extraction runs in the download list with its progress, and the song takes the video's place in the audio folder: a single video's song goes straight into it, and a playlist video's into a folder of the playlist's name.

**Remove** in the same menu takes a download off the list and always deletes its unfinished parts. A cancelled or failed download that saved nothing goes at once; an unfinished one asks first; one that saved files asks too, and **Also move the saved files to the Recycle Bin** sends them there with their captions and lyrics (left unticked, they stay in the folder and the Library).

---

## Built-in Players

**Play** in the Library, or on a finished download, opens videos in the player window and songs in the music bar at the bottom of the app; **Play all** plays the list as filtered. Both continue where a file last stopped, and **Open in another player** uses the program Windows chooses.

- **Video player**: its own window, so downloads stay in view. Subtitles (embedded, or files saved beside the video), audio tracks, speed from 0.25× to 2×, loop, keep on top, and fullscreen. Portrait videos open in a portrait window.
- **Music player**: cover art, previous and next, shuffle, repeat the list or one song, speed, and volume. **Lyrics and up next** opens the Now playing view: a large cover, lyrics that light up and scroll with the song (click a line to jump to it), and the play order.

| Key (video player) | Action |
|---|---|
| Space or K | Play or pause |
| J / L | Back or ahead 10 seconds |
| Left / Right | Back or ahead 5 seconds |
| Up / Down | Volume |
| M | Mute |
| F (Esc leaves) | Fullscreen |
| C | Next subtitle choice |
| [ / ] | Slower or faster |
| P / N | Previous or next video |

Media keys play, pause, and skip songs while the app is in front, and the tray menu plays or pauses the music. The players use Qt Multimedia with FFmpeg, decoding on the graphics card where it can.

---

## Shorts, Reels, and Other Sites

Paste a link from any site yt-dlp supports. These short-form and social links are recognized, cleaned of share-tracking parameters, and saved as described in [Where Files Go](#where-files-go):

| Site | Links |
|---|---|
| YouTube | Shorts (`/shorts/`), and channels' Shorts tabs |
| TikTok | Videos and photo posts (`/@user/video/`), share links (`vm.tiktok.com`), and profiles (`/@user`) |
| Instagram | Reels (`/reel/`, `/reels/`), posts including carousels (`/p/`), and stories (needs a sign-in) |
| Facebook | Reels (`/reel/`, `/share/r/`), videos (`/watch`, `/videos/`, `fb.watch`) |
| X (Twitter) | Posts with one or more videos (`/status/`), and `t.co` links |
| Snapchat, Pinterest, Reddit | Spotlight, pins (`pin.it`), and posts (`v.redd.it`) |

Posts with only pictures are skipped with a clear message. Many Instagram and Facebook posts, and some TikToks and X posts, need a sign-in to the site; sites protected with DRM (Netflix, Spotify) can't be downloaded.

---

## Signing In to Sites

Some videos need an account: your own private playlists, Watch later, and Liked videos, members-only and age-restricted videos on YouTube, and most posts on Instagram and Facebook. When a link or a download needs a sign-in, it stops with a **Sign in** button instead of retrying, and continues by itself once you have signed in. If a video of a signed-in playlist fails to download with the sign-in, the app downloads it once more by its own link without it, into the playlist's folder.

On the **Sign-ins** page, click **Sign in** next to the site. The site's sign-in page opens in your default browser (Edge, Chrome, Brave, Vivaldi, or Firefox; otherwise Edge), in a window of its own with its own profile, so your everyday browsing isn't touched. Sign in there, then click **Done** in the app: it closes that window and saves the sign-in. A YouTube sign-in is then checked by opening Watch later, and the site's card offers **Watch later**, **Liked videos**, and **Your playlists** to download from.

**Other ways** (the `…` button) offers:

| Method | How it works |
|---|---|
| **Another browser window** | The same, in another installed browser. **Refresh** renews a browser-window sign-in later without a window, and the app does it by itself once when a download finds the sign-in expired. |
| **Companion extension** | Open the site signed in, click the extension, and choose **Sign this site in to the app**. Works with the browser you use every day. |
| **Firefox** | Downloads read your everyday Firefox's sign-in each time. |
| **Cookies file** | Import a `cookies.txt` exported from a browser; the app offers to move the original to the Recycle Bin. |

The browser window is your own browser on a profile of its own, so sites such as Google treat it like any browser; Google refuses sign-ins in browsers built into apps, which is why the app doesn't use one. Because that profile isn't used for browsing, YouTube doesn't replace the session, and the sign-in keeps working. For YouTube through the extension, use a private window that you close afterwards for the same reason.

Sign-ins are saved encrypted for your Windows account (DPAPI), so a copied file is useless on another account or PC. Each download receives only its own site's cookies, in a file deleted when the download ends. **Sign out** deletes the sign-in from this PC; signing out on the site itself also ends the session there.

---

## Subscriptions

On the **Subscriptions** page, subscribe to a channel or playlist with a preset and a check interval (every hour to once a day). By default only uploads from now on download; turn on **Earlier uploads too** to get the whole channel first. New uploads join the queue on their own, or wait for **Download new** when automatic downloads are off. Scheduled streams and premieres wait in the queue and record when they start.

A subscription shares its archive with downloads of the same channel, so nothing downloads twice. A channel is checked newest first and stops at the first upload you have; a playlist is read whole each time (up to 2,000 videos), since new videos are usually added at its end. Checks run while the app is open or in the tray; turn on **Start with Windows** to keep checking after a restart. Import your YouTube subscriptions from [Google Takeout](https://takeout.google.com/)'s `subscriptions.csv`, or export and import the app's own list.

---

## Scheduling and When-Done

- **Start downloads at** (Preferences > Network and schedule): new downloads wait until that time; **Start now** in the bottom bar overrides it.
- **Speed limits by time of day**: for example 500 KB/s from 09:00 to 18:00. The limit is shared by every running download; live recordings are never slowed.
- **When downloads finish**: quit the app, sleep, hibernate, or shut down, chosen in the bottom bar, after a 60-second countdown you can cancel.
- **Keep the PC awake while downloading** (Preferences > Downloads, on by default): Windows doesn't sleep or hibernate on its own while downloads run or wait to try again. The screen can still turn off, and Sleep in the Start menu still works.

---

## Live Streams

The download options show **Live now** or **Starts** for streams. A live stream records from its beginning where the site allows it; a scheduled stream or premiere waits in the queue and starts recording on time. MKV is used for recordings, since it stays playable even when a recording stops early.

---

## Companion Browser Extension

The companion adds a toolbar button and a right-click entry to Chrome, Edge, Opera, Brave, and Vivaldi:

- **Download this page**, or right-click a link or video: the app downloads it with your default preset.
- **Sign this site in to the app**: sends that site's cookies to the app. The extension asks for permission to read that one site's cookies on that click and gives the permission back right after.

The installers connect the extension to the app. Until the extension is in the Chrome Web Store, load it from the release's zip: unzip it, open `chrome://extensions`, turn on Developer mode, and choose **Load unpacked**.

---

## Command Line

The installers can add `gfgmd` to PATH (an option on the last page), and the portable `.7z` includes `gfgmd.exe`. From source, run `python -m gfgmd.cli`. The original script's options keep their names and defaults:

```powershell
gfgmd "https://www.youtube.com/playlist?list=PLAYLIST_ID"
gfgmd "https://youtu.be/VIDEO_ID" -r 720 -c 4
gfgmd "https://music.youtube.com/playlist?list=PLAYLIST_ID" --audio
gfgmd "https://www.tiktok.com/@user/video/VIDEO_ID"
gfgmd "https://vimeo.com/123456" --subs "en.*" --embed-subs --limit-rate 2M
```

| Option | Default | What it does |
|---|---|---|
| `URL` | (required) | A video, Short, playlist, or channel, or a page on another site |
| `-r`, `--resolution HEIGHT` | `1080` | Highest resolution on the shorter side; `0` for the best |
| `--output-dir PATH` | `Videos\gfgRoyal Media Downloader` (`Music\…` for audio) | Download root (the original script's folder is kept when it exists) |
| `-c`, `--concurrent-fragments N` | `8` | Pieces of a video downloaded at the same time, 1 to 16 |
| `--max-attempts N` | `0` | Attempts before giving up on temporary failures; `0` keeps trying |
| `--retry-delay SECONDS` | `10` | First wait between attempts; it doubles up to five minutes |
| `--cookies PATH` | | A `cookies.txt` sign-in file saved from your browser |
| `--cookies-from-browser BROWSER` | | Read the sign-in from a browser, such as `firefox` |
| `--audio [FORMAT]` | `mp3` | Audio only: `mp3`, `m4a`, `opus`, `vorbis`, `flac`, `wav`, or `best` (unconverted) |
| `--audio-quality KBPS` | `320` | Audio quality in kbps for MP3, M4A, Opus, and OGG: 320, 256, 192, 160, 128, 96, or 64 |
| `--cover square\|original`, `--no-cover` | `square` | The audio file's cover from the thumbnail |
| `--no-lyrics`, `--no-online-lyrics` | | Skip lyrics, or use only the site's captions for them |
| `--container`, `--codec` | `mp4`, `balanced` | Video file type, and compatible, balanced, or best quality |
| `--audio-langs LANGS` | | Keep dubbed audio tracks too, such as `es,pt-BR` (MP4 or MKV) |
| `--subs LANGS`, `--auto-subs` | | Subtitles in these languages, and automatic captions |
| `--embed-subs`, `--keep-subs`, `--sub-format srt\|vtt` | | Embed subtitles, embed and keep the files, and the files' format |
| `--embed` | | Embed the thumbnail, details, and chapters |
| `--sponsorblock mark\|remove` | | SponsorBlock on YouTube |
| `--limit-rate RATE`, `--proxy URL`, `--force-ipv4` | | Network |
| `--items SPEC` | | Which playlist videos, by number, such as `1:5,8` |
| `--live-from-start`, `--wait-for-video` | | Live streams |
| `--strict` | | Exit with status 1 when any video couldn't be downloaded |
| `-v`, `--verbose` | | Also print yt-dlp's warnings and its own error text |
| `--json` | | One JSON object per line on stdout, for scripts and AI agents (below) |

Progress reads like `Video 2 of 8  Downloading  45% of 40.0 MB  2.1 MB/s  about 1 minute left`, and a video that can't be downloaded is named with the reason. Exit status: `0` when every available video was saved (private or removed ones are listed but don't fail the run unless `--strict`), `1` when failures remain after `--max-attempts`, `2` when the link, the tools, or the folders can't be used, and `130` after Ctrl+C. The command line uses the app's managed tools when the app is installed, otherwise yt-dlp, FFmpeg, and Deno on PATH. It needs only Python's standard library, so it also runs on Linux.

### For Scripts and AI Agents

With `--json`, stdout carries one JSON object per line and nothing else: `start`, `item`, `progress`, `file` (each saved path), `skipped`, `error`, `warning`, `retry`, and last a `done` event with `ok`, `exit_code`, and the counts. Titles and paths are escaped, so they arrive exact whatever the console's code page.

```powershell
gfgmd "https://youtu.be/VIDEO_ID" --json --max-attempts 3
```

The repository's [`skills/gfgmd`](skills/gfgmd/SKILL.md) is an [Agent Skill](https://agentskills.io) that teaches AI coding agents (Claude Code, Codex, Cursor, GitHub Copilot, Gemini CLI, and others) to use `gfgmd`: finding it, the common downloads, reading the JSON, and when to ask you first. `gfgmd.exe` carries it:

| Command | What it does |
|---|---|
| `gfgmd skill install` | Copies it into `~/.agents/skills` and `~/.claude/skills`, which Codex, Claude Code, Cursor, Cline, and others read |
| `gfgmd skill install --agent NAME` | Into one agent's own folder: `codex`, `cursor`, `copilot`, `gemini`, `windsurf`, `opencode`, `goose`, and more (`gfgmd skill install --help` lists them) |
| `gfgmd skill install --dir FOLDER` | Into any skills folder |
| `gfgmd skill uninstall`, `gfgmd skill path` | Remove it, or list where it is |
| `gfgmd skill show` | Print it, to paste into the instructions of an agent that can't load skills |

Without the app, `npx skills add ShahFaisalGfG/gfgRoyal-Media-Downloader` installs it for any of the agents the open `skills` installer knows.

---

## Where Files Go

Videos go to `Videos\gfgRoyal Media Downloader` and audio to `Music\gfgRoyal Media Downloader` (Preferences > Downloads), wherever Windows keeps those folders. The original script's `Videos\youtube-video-downloader` is used instead when it already holds downloads, so its archives keep working.

A single download goes straight into that folder; anything holding several videos gets a folder of its own. Subscriptions use the same folders as downloading the channel or playlist yourself.

| Download | Folder |
|---|---|
| A video, Short, Reel, TikTok, song, or live recording | The download folder itself |
| A post holding several videos (an X post, an Instagram carousel) | `<post title>\` (a post with one video stays in the download folder) |
| A playlist, including Watch later and Liked videos | `<playlist name>\` |
| A YouTube channel | `<channel>\Videos\`, `Shorts\`, `Live\` |
| A TikTok, Instagram, or X profile | `<account>\` |

Files are named after the title and the quality measured from the finished file, such as `Episode 001 (1080p).mp4`: a 1080p request that was only offered at 720p ends in `(720p)`, and videos that share a title get ` (2)`, ` (3)` instead of overwriting each other. Preferences offers other name styles (title only, date first, playlist number first). Unfinished files wait in the `.incomplete` folder, and per-playlist, per-format archives in `.archives` record what is done; both folders are hidden.

Moving files to the Recycle Bin, from the Library or with **Remove** in Downloads, takes their captions, lyrics, and covers with them, and a playlist's, channel's, or profile's folder goes too once nothing else is in it. The download folder itself always stays.

A video downloaded before isn't downloaded twice: its entry reads **Already downloaded**, and **Play** opens the file you have. When that file is gone (you deleted it), the video downloads again. **Download again** in its menu, or in the Library, downloads it once more anyway.

---

## Quality and Speed

The quality limit applies to the shorter side, so 1080 suits landscape videos and portrait Shorts alike. **Plays everywhere** prefers H.264 video and AAC sound, which every player handles; **Best quality** allows AV1 and VP9, which older devices may not play. Streams download eight pieces at a time by default; **Optimize for this PC** (Preferences > Downloads) measures 4, 8, and 16 on your connection and keeps the fastest. Three downloads run at once by default, with at most two or three per site.

---

## The Download Tools

yt-dlp does the downloading, FFmpeg merges and converts, and Deno solves YouTube's player challenges. The app downloads them from their official GitHub releases ([yt-dlp](https://github.com/yt-dlp/yt-dlp/releases), [yt-dlp's FFmpeg builds](https://github.com/yt-dlp/FFmpeg-Builds/releases), [Deno](https://github.com/denoland/deno/releases)), checks every file against the checksums those projects publish, and keeps them in `%LOCALAPPDATA%\gfgRoyal Media Downloader\tools`. They update once a day and right after a download fails in a way a newer yt-dlp usually fixes. Preferences > Tools shows each version, switches yt-dlp to early fixes (updated daily), goes back to the previous version, or uses programs already installed on this PC or in a folder you choose.

---

## Privacy and Security

- **No accounts, no telemetry, no ads.** The app contacts the sites you download from, GitHub (for its own updates and the tools), LRCLIB for lyrics (title, artist, album, and length only), and nothing else. The [privacy policy](PRIVACY.md) lists each connection; the installers let you turn off the ones the app makes on its own, and Preferences turns them off at any time.
- **No configuration from elsewhere runs.** Every yt-dlp run ignores yt-dlp's own configuration files, plugins, and remote code, and links are always passed after `--`, so nothing can add options such as `--exec`.
- **Verified downloads.** Tools must match their published SHA-256 checksums and come only from GitHub over HTTPS; app updates must carry the release signature.
- **Sign-ins stay on your PC**, encrypted for your Windows account, and are never written to logs. A download that needs one gets a copy for that run only, removed when it ends (and at the next start after a crash). A browser window's sign-in is read over a private pipe, never a network port another program could reach.
- **Your proxy covers the app's own requests.** Lyrics, thumbnails, and tool downloads go through the HTTP proxy set in Preferences > Network, as downloads do (a SOCKS proxy applies to downloads only); app updates follow Windows' proxy settings.
- **Text from sites is only text.** Titles and names are shown as plain text, and nothing a site puts in a title can pose as the app's own progress lines or point it at a file outside the download folder.
- **The tools are never taken from the current folder**, so a program dropped where the command line runs can't stand in for yt-dlp or FFmpeg.
- **No administrator rights** are needed to run the app or to install it for your account.

---

## Code Signing Policy

Free code signing provided by [SignPath.io](https://about.signpath.io/), certificate by [SignPath Foundation](https://signpath.org/).

Releases are built from this repository by GitHub Actions and signed through SignPath once the project is accepted into the SignPath Foundation's program for open-source projects; until then they are unsigned. Signed files name SignPath Foundation as their publisher, and each release is approved by hand before it is signed.

- Committers and reviewers: [Shah Faisal](https://github.com/ShahFaisalGfG)
- Approvers: [Shah Faisal](https://github.com/ShahFaisalGfG)

Privacy policy: see [PRIVACY.md](PRIVACY.md). This program connects only to the sites you use, GitHub, and LRCLIB, as that page describes.

---

## Troubleshooting

| Message | What to do |
|---|---|
| **Sign-in needed** / **This is private. Sign in with an account that can see it** | Sign in to the site on the Sign-ins page; waiting downloads and the link you opened continue on their own |
| **This post has only pictures, no video** | The post has no video to save; it's skipped |
| **The site wants to check that you aren't a bot** | The app updates its download tools and tries again; signing in to the site usually ends these checks |
| **The site is getting too many downloads from you** | Downloads from that site wait and resume; lower **Downloads at once** if it keeps happening |
| **This is private** / **removed** / **isn't available in your country** | The video is skipped; the rest of the playlist continues |
| **Waiting for its server** / **The download server didn't answer** | The site sent the video from a server that isn't answering your PC; the rest of the list downloads first, then it tries again with fresh links. If it keeps happening, pause and resume the download later |
| **The drive is full** | Downloads pause; free some space or choose another folder, then **Resume all** |
| **The app isn't allowed to save in this folder** | Click **Choose folder** on the download, or allow the app in Windows Security > Ransomware protection |
| **The download folder can't be reached** | Plug in the drive the folder is on, or click **Choose folder** on the download |
| **The download tools are missing or damaged** | Click **Update tools** on the download, or Preferences > Tools > **Update tools** (**Download tools** when they're missing); **Previous version** after a bad update |

Still stuck? [Open an issue](https://github.com/ShahFaisalGfG/gfgRoyal-Media-Downloader/issues) with the link (if you can share it) and, with logging turned on in Preferences, the last lines of the log, which hold yt-dlp's own words for each failure. Logs never contain your sign-ins.

---

## Building from Source

```powershell
git clone https://github.com/ShahFaisalGfG/gfgRoyal-Media-Downloader.git
cd gfgRoyal-Media-Downloader
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m gfgmd
```

Running from source keeps settings next to the code and the library and tools in `build\local`, so it never touches an installed copy.

| Command | What it does |
|---|---|
| `python -m pytest` | Every test, with Qt offscreen (`$env:QT_QPA_PLATFORM = "offscreen"`); a fake yt-dlp means no test contacts a site |
| `python -m pytest tests/core tests/test_cli.py` | The engine and command line only (no PySide6 needed, also on Linux) |
| `pyright gfgmd` | Type check |
| `pyside6-qmllint -I gfgmd/qml -I gfgmd/qml/components <files>` | QML lint |
| `python scripts/make_icons.py` | Redraw the app's and the extension's icons |
| `./scripts/build.ps1` | Both installers and the portable exe (needs Inno Setup 6) |

The companion extension is in `companion/` (Node.js 22): `npm install`, `npm run build`, `npm run typecheck`, `npm run lint`, `npm test`, and `npm run test:e2e`.

Versions follow [Semantic Versioning](https://semver.org/); the version lives in `pyproject.toml`, and a `v<version>` tag builds and publishes a release with its notes from `release_notes/`. Every exe the build makes carries the app's name as its product name and the version from `pyproject.toml`.

### Signing releases

The release workflow signs through SignPath when the repository has the variables `SIGNPATH_ORGANIZATION_ID`, `SIGNPATH_PROJECT_SLUG`, and `SIGNPATH_POLICY_SLUG` and the secret `SIGNPATH_API_TOKEN`; without them it publishes unsigned files. Each release makes two signing requests, and each waits up to two hours for approval in SignPath:

1. The app's programs (`gfgRoyal-Media-Downloader.exe`, `gfgmd.exe`, and the companion's host), before the installers are built from them.
2. Both installers and the portable exe.

The SignPath project takes its artifact configurations from `.signpath/artifact-configurations/`: `programs.xml` under the slug `programs` and `packages.xml` under `packages`. Both accept a file only when its product name is the app's and its product version is the release's.

---

## Roadmap

| Target | Plan |
|---|---|
| **1.0.x** | Fixes and polish from the first users |
| **Companion** | Chrome Web Store listing |
| **Later** | Per-subscription folders and file names, more languages for the interface |

Have a feature idea? [Open an issue](https://github.com/ShahFaisalGfG/gfgRoyal-Media-Downloader/issues).

---

## Changelog

### Unreleased
- 🤖 `gfgmd --json` reports in JSON lines for scripts and AI agents, `gfgmd --help` shows examples, and `gfgmd skill install` installs the [Agent Skill](skills/gfgmd/SKILL.md) that teaches Claude Code, Codex, Cursor, and other agents to use `gfgmd`

### v1.0.0 - November 2026 *(current)*
- 🖥️ The first release of the desktop app: queue, Options panel, Library, Subscriptions, Sign-ins, Preferences, tray, notifications, and in-app updates
- 🌐 Every site yt-dlp supports, with YouTube channels and their tabs, and TikToks, Reels, X posts, and other short-form links
- 🎵 Music as MP3 320 kbps or other formats and bitrates, with square covers, tags, and synced lyrics
- ▶️ Built-in video and music players
- 🗣️ Dubbed audio tracks and subtitle choices for videos
- 🔑 Website sign-ins, subscriptions, scheduling, live recording, and the companion extension
- 🧰 yt-dlp, FFmpeg, and Deno downloaded, verified, and kept current by the app
- ⌨️ `gfgmd` replaces the YouTube Video Downloader script (`download_playlist.py`) with the same options and new ones; yt-dlp configuration files and plugins are always ignored (the script still loaded `config.txt`), and private or removed videos no longer keep a run retrying forever; Python 3.12 or later

Re-released on 23 November 2026 with these changes since its first build of 19 November. The in-app updater sees the same version number, so install this build over the first one to get them; your library, settings, and sign-ins stay.

- 🎵 **Extract audio** from a downloaded video, with the same format, cover, tag, and lyrics choices as an audio download
- 🗑️ **Remove** deletes a download's unfinished parts, asks only for unfinished downloads or ones with saved files, and can move saved files to the Recycle Bin; Cancel now also deletes a paused download's unfinished files
- 🎬 The default preset is **Video, best quality MP4**, which replaces the 1080p and 720p MP4 presets
- ☑️ Select several downloads or library files (boxes on the thumbnails, Ctrl+click, Shift+click, Ctrl+A) and act on them together; songs and videos are told apart by their cover shape and a type badge
- 🔽 **Options** became the arrow on the **Download** button, which opens the download options for the link and closes them again
- 🔗 The link box holds a paste button while it is empty, takes only characters a link can hold (spaces and line breaks are dropped), and keeps several pasted links together as **+N more**
- ⚙️ Preferences lists its sections down the side (General, Downloads, Video, Audio, Network and schedule, Subscriptions, Tools, Updates and logs)
- 🗂️ **Downloads** holds work in progress and this session's finished downloads, which leave it when you quit (the Library keeps them); **Clear finished** sits above the list
- 📁 Single downloads go straight into the download folder; playlists, channels, profiles, and posts with several videos get folders of their own, and the `.archives` and `.incomplete` folders are hidden
- ♻️ A video downloaded before reads **Already downloaded** and plays the file you have, or downloads again when you deleted its file; **Download again** (in its menu and the Library) downloads it anyway, and a link already waiting in the list isn't added twice
- 📊 Audio downloads show how far the conversion has got, and the progress bar moves on downloads whose size the site doesn't list
- 📜 A playlist, channel, or several new subscription uploads list every video under one download, numbered, with each one's state, progress, and Play button; finished songs reach the Library and get their clean names as they land, not when the whole list ends
- 🗄️ The Library groups each playlist's and channel's files in one row that opens into them in the playlist's order, with **Play all**; a search opens the groups that hold matches
- ⏭️ A video whose download stops moving (its server stopped answering) waits while the rest of the list downloads, then tries again with fresh links; the progress bar counts what is saved and no longer jumps back between tries
- 💬 Every status, step, and message is in plain words: "Song 2 of 8", "about 3 minutes left", "Putting the video together", "Preparing the cover", and errors that say what to do, with tool output, codes, and file paths kept for the log
- 🔔 Playlist subscriptions read the whole playlist, so videos added at its end are found even when its first ones were downloaded before, and new uploads go in the playlist's own folder; uploads from sites other than YouTube are kept for **Download new**; the Subscribe dialog keeps a link it can't take and says why, including "You're already subscribed to this"
- 🚪 **Ctrl+Q** quits (asking first while downloading), the first close to the tray says the app is still running there, the tray's **Quit** quits even with the window open, and downloads stopped by quitting start again as soon as the app opens
- 🎧 Songs drop video clutter such as "(Official Video)" and "(Lyrics)" from their names and tags, and YouTube's quieter "stable volume" audio copy is never picked when the full one is offered
- ♻️ **Download again** in the Library keeps the file's own type (a song stays a song, an MKV stays an MKV) and says it was added; Choose folder on a download that couldn't save changes the folder of its own type
- ⌨️ Keyboard and screen reader use: the Download options video list, page tabs, Preferences sections, and every list's menu (Menu key or Shift+F10) work from the keyboard; notices are read out; text boxes have names; selected rows say so; focus never scrolls out of sight; toggle buttons show when they are on
- 🛡️ Reliability: a file that couldn't be finished, or a subtitle another program held open, no longer stops a download or loses its file; a playlist video that keeps failing is skipped after three tries instead of retrying the list forever; Cancel and Remove stay what they are when you quit right after; a download folder on an unplugged drive says so and offers **Choose folder**; the Library and long playlists stay fast
- ⌨️ `gfgmd` accepts links typed without `https://`, numbers retries by failed attempts only, and says a reason once
- 🛡️ Lyrics, thumbnails, and tool downloads use the proxy set in Preferences; a browser window's sign-in is read over a private pipe instead of a local debugging port; check boxes and radio buttons match the rest of the app and show a focus ring
- 🔁 A video of a signed-in playlist that fails with the sign-in (YouTube's signed-in downloads can break off partway) is downloaded once more by its own link without it, into the playlist's folder, so a song that downloads on its own also downloads in its playlist; with logging on, the log holds yt-dlp's own words for each failure
- 🔁 A playlist video that keeps breaking off with an error that doesn't name it (a missing part, "HTTP Error 403") is given up on like any other, so the list finishes; a download waiting to try again says why ("Trying again in 5 minutes · The connection dropped"); a list's videos you already have show **Downloaded before** as the list is read (yt-dlp's current wording, which names each one, wasn't recognized), and the summary leaves out a count of nothing saved ("7 downloaded before, 1 couldn't be downloaded"); a finished download deletes what earlier attempts left unfinished of the videos it saved, and a download leaving the list takes its other unfinished files with it
- ⌨️ Where a message points at the app's window (sign in, choose a folder, wait for a stream), `gfgmd` names its own option instead (`--cookies`, `--output-dir`, `--wait-for-video`)
- 🔏 A [privacy policy](PRIVACY.md) lists every connection the app makes; the installers show it and let you turn off app update checks, download tool updates, and online lyrics, and connecting the companion extension is an installer choice too. Every exe carries the app's name and version, and releases are ready to be signed through SignPath ([Code signing policy](#code-signing-policy))
- 🗑️ Moving a playlist's, channel's, subscription's, or profile's files to the Recycle Bin removes its folder once it is empty (a channel's folder goes with its last tab folder; the download folder stays); WAV playlists no longer save the playlist's own cover beside their songs, which kept the folder; the empty folders yt-dlp leaves in `.incomplete` are removed when a download ends; and a video whose server never sent anything no longer leaves its thumbnail and empty part there once its download leaves the list
- ☕ **Keep the PC awake while downloading** (on by default) explains in Preferences what it does: no sleep or hibernation on its own while downloads run or wait to try again
- 🐞 Fixed: choosing Audio only in the download options froze the app, then made two of its rows blink; a single click in the video player paused before a double click went fullscreen; download menus cut their text off; ticking a download in progress let go of it a moment later; a step yt-dlp names without "FFmpeg" read "Processing"; a YouTube playlist subscription's uploads went to a folder named "NA"; "Download again" could fetch a song twice after a retry

[Full release notes →](release_notes/)

---

## Responsible Use

Download only videos you own or have permission to save, and follow each site's terms and the copyright law where you live. This project is not affiliated with or endorsed by YouTube, Google, or any other site.

---

## License & Credits

Released under the [MIT License](LICENSE): free to use, modify, and distribute. Bundled components and the separately downloaded tools are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Downloads are made by [yt-dlp](https://github.com/yt-dlp/yt-dlp), with [FFmpeg](https://ffmpeg.org/) for merging and probing and [Deno](https://deno.com/) for YouTube's JavaScript challenges.

Built with ❤️ by **Shah Faisal** · [Portfolio](https://shahfaisalgfg.github.io/) · [LinkedIn](https://www.linkedin.com/in/shahfaisalgfg) · [shahfaisalgfg@gmail.com](mailto:shahfaisalgfg@gmail.com)

---

*Paste once. Come back to a finished playlist.* 📥
