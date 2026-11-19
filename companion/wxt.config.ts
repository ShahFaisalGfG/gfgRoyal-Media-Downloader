import { resolve } from 'node:path';
import { defineConfig } from 'wxt';

/** License texts that must ship with the extension, which bundles MIT-licensed WXT code. */
const LICENSE_FILES = ['LICENSE', 'THIRD_PARTY_NOTICES.md'];

/**
 * The public half of the development signing key. It fixes the extension ID
 * (gipopofnfbdhmmkpeaffnjfkkdbnjepp) so the app's native host can allow exactly this extension
 * before store publication; it is not a secret.
 */
const MANIFEST_KEY =
  'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA14pGG2sHHX6YpSisBcjKDV8iwUTBvBOvdhcHLEUSHR5Jh+iin1OXO3UnQfixHJYz+2pW2ArB1gSVm2Mnoivx6jF0XOJtvI78O/L5wTd3GFf7U4dvhcyqzqwaANfyWq/Vu1soaslZO7cWk/EhlB/ySIAi6RZzvXXx1UOorRV04cZnT7YqElipEVj/VFE5AE/0H5tnSBrRKewNZbJgI4Y+h41d29V0QHYnjJWAuKqt3R9tPr0yEhVftf99GibKJHiduAdR2hmeJlnnfVmjY1aTAvXprmyqvGIoXDesQMup7/BCGAtVJtY5HzHpVohA14dMADNQE/0BgQTFEpf9Bp7LAQIDAQAB';

export default defineConfig({
  srcDir: 'src',
  hooks: {
    'build:publicAssets': (_wxt, files) => {
      for (const name of LICENSE_FILES) files.push({ absoluteSrc: resolve(name), relativeDest: name });
    },
  },
  manifestVersion: 3,
  targetBrowsers: ['chrome'],
  zip: {
    artifactTemplate: 'gfgRoyal-Media-Downloader-Companion_{{version}}_{{browser}}.zip',
  },
  manifest: {
    key: MANIFEST_KEY,
    name: 'gfgRoyal Media Downloader Companion',
    short_name: 'Media Downloader',
    description: 'Send videos, playlists, and channels to gfgRoyal Media Downloader, and sign sites in to the app.',
    author: { email: 'shahfaisalgfg@gmail.com' },
    homepage_url: 'https://github.com/ShahFaisalGfG/gfgRoyal-Media-Downloader',
    minimum_chrome_version: '116',
    permissions: ['nativeMessaging', 'contextMenus', 'activeTab'],
    // Asked for only when the user signs a site in, and only for that site.
    optional_permissions: ['cookies'],
    optional_host_permissions: ['https://*/*', 'http://*/*'],
    incognito: 'spanning',
    action: {
      default_title: 'gfgRoyal Media Downloader',
      default_icon: {
        16: 'icon/16.png',
        32: 'icon/32.png',
        48: 'icon/48.png',
        128: 'icon/128.png',
      },
    },
  },
});
