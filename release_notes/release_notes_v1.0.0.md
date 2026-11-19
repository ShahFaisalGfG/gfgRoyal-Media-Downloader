# gfgRoyal Media Downloader v1.0.0 - Release Notes

**Released:** November 2026 · **Status:** Stable · **Platform:** Windows 10 version 1809 or later (64-bit); the `gfgmd` command line also runs on Linux

---

v1.0.0 is the first release of gfgRoyal Media Downloader, which grew out of the YouTube Video Downloader command-line script: a desktop app for video and music from YouTube, TikTok, Instagram, Facebook, X, and every other site yt-dlp supports, with a queue, built-in players, synced lyrics, subscriptions, website sign-ins, scheduling, live recording, and a companion browser extension. The command line stays as `gfgmd`.

---

## Features

- **Downloads page.** Paste a link and press Download with a preset, or open Options to choose quality (up to 4K), container (MP4, MKV, WebM), codecs, the original audio track or dubbed languages too, subtitles (languages, embedded, SRT or WebVTT files, or both), embedded thumbnail, details and chapters, SponsorBlock, and which videos of a playlist or channel to get.
- **Music.** MP3 at 320 kbps by default, or 64 to 256 kbps, M4A, Opus, OGG, lossless FLAC or WAV, or the site's own stream; a square cover from the thumbnail, artist and title tags, and audio saved to `Music\gfgRoyal Media Downloader`.
- **Synced lyrics.** Songs get a timed `.lrc` file from the site's captions, or from LRCLIB when the track length matches, plus plain lyrics in MP3, M4A, and FLAC tags.
- **Built-in players.** A video window with subtitles, audio tracks, speed, keep on top, and fullscreen; a music bar with a queue, shuffle, repeat, and a Now playing view whose lyrics follow the song. Both resume where a file stopped.
- **Shorts and social links.** TikToks and TikTok profiles, Instagram and Facebook Reels and posts, X posts, Snapchat Spotlight, Pinterest, and Reddit links are recognized, cleaned of share tracking, and saved in their own folders.
- **Queue.** Several downloads at once with per-site limits; pause, resume, retry, reorder, cancel (which deletes unfinished files), and progress on the taskbar. Interrupted downloads resume when the app starts again.
- **Smarter failures.** Private, removed, and region-locked videos are skipped and listed; sign-in requests stop the download with a Sign in button; a full disk pauses the queue; out-of-date yt-dlp is updated and the download tried again.
- **Sign-ins.** One click opens the site in your default browser on a profile of its own; sign in and click Done. Private playlists, Watch later, Liked videos, and members-only or age-restricted videos then download, and a link that needed the sign-in is read again by itself. The companion extension, Firefox, and cookies files are other ways in. Sign-ins are encrypted for your Windows account and each download receives only its site's cookies.
- **Subscriptions.** Watch channels and playlists for new uploads on a schedule, import YouTube Takeout's list, and export or import the app's own.
- **Scheduling.** Start the queue at a time, limit speed by time of day, and sleep, hibernate, shut down, or quit when everything is done.
- **Live streams.** Record from the start, or wait for a scheduled stream or premiere.
- **Library.** Search finished downloads; play here or in another player, play all, show in folder, download again, or move to the Recycle Bin.
- **Tools.** yt-dlp, FFmpeg, and Deno download on first use from their official releases, checked against their published checksums, and stay current (stable or nightly yt-dlp, with a way back to the previous version).
- **Companion extension.** Download the current page or a right-clicked link, and sign sites in, from Chrome, Edge, Opera, Brave, or Vivaldi.
- **App.** Light and dark themes, keyboard shortcuts, tray icon, notifications, Start with Windows, in-app signed updates, and portable builds.

## Coming from the YouTube Video Downloader script

- `download_playlist.py` is replaced by the `gfgmd` command (`gfgmd.exe` in the installed app, `python -m gfgmd.cli` from source) with the same options and defaults, plus new ones. Python 3.12 or later.
- yt-dlp's configuration files and plugins are now always ignored; the script still loaded `%APPDATA%\yt-dlp\config.txt`.
- A run whose only failures are private or removed videos ends with status 0 and lists them, instead of retrying forever; `--strict` makes them fail the run.
- Videos go to `Videos\gfgRoyal Media Downloader` and audio to `Music\gfgRoyal Media Downloader`; an existing `Videos\youtube-video-downloader` keeps being used, with its archives.

## Install

- `gfgRoyal-Media-Downloader_1.0.0_user_installer.exe`: for your account, no administrator rights
- `gfgRoyal-Media-Downloader_1.0.0_system_installer.exe`: for every account on the PC
- `gfgRoyal-Media-Downloader_1.0.0_portable.exe`: one file, keeps its data beside itself
- `gfgRoyal-Media-Downloader_1.0.0_portable.7z`: the same, unpacked, with `gfgmd.exe`
- `gfgRoyal-Media-Downloader-Companion_1.0.0_chrome.zip`: the companion extension, loaded unpacked until its store listing

## Known limitations

- The companion extension isn't in the Chrome Web Store yet; load it unpacked.
- Subscriptions are checked only while the app runs (in the tray, or after Start with Windows).
- Sites change often; when one stops working, a newer yt-dlp usually fixes it, and the app installs it automatically.

---

*Paste once. Come back to a finished playlist.* 📥
