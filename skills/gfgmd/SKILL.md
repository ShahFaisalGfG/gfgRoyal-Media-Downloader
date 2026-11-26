---
name: gfgmd
description: Download videos, music, playlists, channels, Shorts, Reels, TikToks, and live streams from YouTube and the other sites yt-dlp supports, with gfgmd, the command line of gfgRoyal Media Downloader. Use it when the user asks to download, save, or archive a video or its audio (MP3, M4A, FLAC, WAV), a whole playlist or channel, subtitles, or song lyrics from a link.
license: MIT
compatibility: Windows 10 or 11 with gfgRoyal Media Downloader installed (or its portable 7z); elsewhere from source with Python 3.12 and yt-dlp, FFmpeg, and Deno on PATH.
metadata:
  version: "1.0.0"
  homepage: https://github.com/ShahFaisalGfG/gfgRoyal-Media-Downloader
---

# gfgmd

`gfgmd` downloads what a link points to: one video, a playlist, a channel, a profile, or a post, from YouTube and every other site yt-dlp supports. It saves clean file names (a video's carries its measured quality: "Talk (1080p).mp4"), keeps a playlist or channel in a folder of its own, and resumes an interrupted download when the same command runs again.

## Find the command

1. `gfgmd --version`: the installers can add it to PATH.
2. Otherwise run it from the install folder:
   - `%LOCALAPPDATA%\Programs\gfgRoyal Media Downloader\gfgmd.exe` (installed for one user)
   - `%ProgramFiles%\gfgRoyal Media Downloader\gfgmd.exe` (installed for all users)
   - `gfgmd.exe` in the folder unpacked from the portable `.7z`
3. From a clone of the repository: `python -m gfgmd.cli` (Python 3.12).

If none is there, tell the user to install gfgRoyal Media Downloader from https://github.com/ShahFaisalGfG/gfgRoyal-Media-Downloader/releases.

## Download

Always add `--json` and quote the link. Add `--max-attempts 3` in automation: the default `0` keeps retrying temporary failures until the download finishes.

```powershell
gfgmd "https://youtu.be/VIDEO_ID" --json --max-attempts 3
gfgmd "https://youtu.be/VIDEO_ID" -r 720 --json
gfgmd "https://youtu.be/VIDEO_ID" -r 0 --container mkv --json
gfgmd "https://youtu.be/VIDEO_ID" --audio --json
gfgmd "https://youtu.be/VIDEO_ID" --audio flac --output-dir "D:\Music" --json
gfgmd "https://www.youtube.com/playlist?list=PLAYLIST_ID" --items 1:5 --json
gfgmd "https://www.youtube.com/@CHANNEL/videos" --items 1:3 --json
gfgmd "https://youtu.be/VIDEO_ID" --subs "en.*" --embed-subs --json
gfgmd "https://www.tiktok.com/@USER/video/VIDEO_ID" --json
```

- `-r HEIGHT` caps the shorter side (default 1080; `0` is the best there is).
- `--audio [FORMAT]` saves audio only: MP3 at 320 kbps by default, with a square cover, artist and title tags, and synced lyrics (`.lrc`) when the site or LRCLIB has them.
- Video goes to `Videos\gfgRoyal Media Downloader`, audio to `Music\gfgRoyal Media Downloader`, unless `--output-dir` names another folder (made if it doesn't exist). A single video lands in that folder; a playlist, channel, or profile gets a folder of its own inside it.
- The download folder also gets working folders: `.archives` (what was downloaded), `.incomplete` (unfinished parts), and `.gfgmd` (the command line's resume state). Leave them: they make a rerun resume and skip what is done.
- A video downloaded before into the same folder with the same choices is skipped as already downloaded.

Every option is in [references/commands.md](references/commands.md).

## Read the result

With `--json`, stdout carries one JSON object per line and nothing else. Read the `file` events for the saved paths (each names the media file; its lyrics `.lrc`, subtitles, and cover sit beside it under the same name) and the last line, the `done` event, for the outcome:

```json
{"event": "file", "path": "C:\\Users\\me\\Videos\\gfgRoyal Media Downloader\\Talk (1080p).mp4", "id": "VIDEO_ID", "title": "Talk"}
{"event": "done", "ok": true, "exit_code": 0, "message": "Finished: 1 video saved. The files are in C:\\Users\\me\\Videos\\gfgRoyal Media Downloader", "state": "done", "saved": 1, "skipped": 0, "attempts": 1, "output_dir": "C:\\Users\\me\\Videos\\gfgRoyal Media Downloader"}
```

`skipped` events name videos that can never download (private, removed, region-locked); `error` events explain problems in plain words. All event fields are in [references/json-events.md](references/json-events.md).

## Exit status

| Code | Meaning |
|---|---|
| `0` | Every available video was saved. Private or removed ones are listed as skipped but don't fail the run, unless `--strict`. |
| `1` | Failures remain after `--max-attempts`, or `--strict` and something was skipped. |
| `2` | The link, the options, the download tools, or the folder can't be used. Usage errors print to stderr with no JSON. |
| `130` | Stopped with Ctrl+C. Run the same command to resume. |

## Rules for agents

- A download can take minutes to hours. Run it in the background or with a long timeout, and don't stop and restart it to "fix" slowness: the same command resumes where it stopped.
- Playlists and channels can hold thousands of videos. Ask the user before downloading a whole channel, and use `--items` to take a few.
- A link to a video watched inside a playlist (`watch?v=...&list=...`) downloads only that video, with a `warning` event saying so. If the user may want the playlist, ask which one they mean; add `--whole-playlist` for every video.
- Sign-in is only for links that need it (private playlists, members-only or age-restricted videos). Use `--cookies-from-browser firefox` or `--cookies FILE` only with the user's agreement, and never ask for a password.
- Download only what the user has the right to download.
- When the tools are missing (exit 2, "The download tools aren't installed"), the user opens the app once to install them.

## The skill itself

```powershell
gfgmd skill install
gfgmd skill install --agent cursor
gfgmd skill show
```

`gfgmd skill install` copies this skill into `~/.agents/skills` and `~/.claude/skills`; `--agent NAME` or `--dir FOLDER` choose other folders, and `gfgmd skill show` prints it for agents that can't load skills.
