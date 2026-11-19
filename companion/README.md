# gfgRoyal Media Downloader Companion

A Chromium extension (Chrome, Edge, Opera, Brave, Vivaldi) for [gfgRoyal Media Downloader](../README.md):

- **Download this page**, or right-click a link, video, or page: the app downloads it with your default preset.
- **Sign this site in to the app**: sends the current site's cookies to the app, so its members-only, private, or
  age-restricted videos download. The extension asks for permission to read that one site's cookies on the click and
  gives the permission back right after; it keeps no cookie access and stores nothing.

It talks to the app through the native-messaging host `com.gfgroyal.mediadownloader`
(`gfgRoyal-Media-Downloader-host.exe`), which the app's installers register for this extension's ID,
`gipopofnfbdhmmkpeaffnjfkkdbnjepp`. The `key` in `wxt.config.ts` fixes that ID; it is the public half of a key pair
and not a secret. The host checks the sender and every message, then hands links or cookies to the running app
(starting it in the tray when needed).

## Develop

Node.js 22 or later.

| Command | What it does |
|---|---|
| `npm install` | Install the tools |
| `npm run dev` | A browser with the extension loaded, rebuilt on save |
| `npm run build` | Build into `.output/chrome-mv3` (the folder to load unpacked) |
| `npm run zip` | The package for the store and the release |
| `npm run typecheck`, `npm run lint` | Checks |
| `npm test` | Unit tests (Vitest) |
| `npm run test:e2e` | Browser tests with the built extension in Playwright's Chromium, on local fixture pages |

The toolbar icons in `public/icon` are drawn by the app's `scripts/make_icons.py`, so the extension and the app share
one design.

## Load it unpacked

Build it (or unzip the release's zip), open `chrome://extensions` (`edge://extensions` in Edge), turn on Developer
mode, choose **Load unpacked**, and select the folder. With the app installed, the popup says it is connected.
