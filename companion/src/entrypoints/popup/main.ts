import { type Browser, browser } from 'wxt/browser';
import { NOT_INSTALLED, ask } from '../../lib/host';
import { downloadMessage, signinMessage } from '../../lib/messages';
import { hostFromUrl, originPatterns, siteForHost } from '../../lib/sites';
import { h, icon } from '../../ui/dom';

/** The active tab, or the tab named by `?tabId=` when the popup is opened as a page (tests). */
async function targetTab(): Promise<Browser.tabs.Tab | undefined> {
  const requested = Number(new URLSearchParams(location.search).get('tabId'));
  if (Number.isInteger(requested) && requested > 0) return browser.tabs.get(requested).catch(() => undefined);
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  return tab;
}

/** The cookies of one site from the tab's own cookie store (a private window has its own). */
async function siteCookies(tabId: number, domains: string[]): Promise<chrome.cookies.Cookie[]> {
  const stores = await browser.cookies.getAllCookieStores();
  const storeId = stores.find((store) => store.tabIds.includes(tabId))?.id;
  const lists = await Promise.all(domains.map((domain) => browser.cookies.getAll({ domain, ...(storeId ? { storeId } : {}) })));
  return lists.flat();
}

async function main(): Promise<void> {
  const app = document.getElementById('app')!;
  const tab = await targetTab();
  const host = hostFromUrl(tab?.url);
  const site = host ? siteForHost(host) : null;
  const tabId = tab?.id;

  const status = h('div', { class: 'status', attrs: { role: 'status', 'aria-live': 'polite' } });
  const setStatus = (kind: 'info' | 'ok' | 'error', text: string): void => {
    status.replaceChildren(
      h('div', { class: `notice notice-${kind}` }, icon(kind === 'ok' ? 'check' : 'info'), h('span', { text })),
    );
  };

  const downloadButton = h('button', {
    class: 'btn btn-primary',
    attrs: { type: 'button', disabled: !host },
    on: {
      click: async () => {
        if (!tab?.url) return;
        downloadButton.disabled = true;
        const reply = await ask(downloadMessage([tab.url]));
        downloadButton.disabled = false;
        setStatus(reply.ok ? 'ok' : 'error', reply.ok ? 'Sent to the app. It downloads with your usual choices.' : reply.message ?? NOT_INSTALLED);
      },
    },
  });
  downloadButton.append(icon('download'), h('span', { text: 'Download this page' }));

  const signinButton = h('button', {
    class: 'btn',
    attrs: { type: 'button', disabled: !site || tabId === undefined },
    on: {
      click: async () => {
        if (!site || tabId === undefined) return;
        const permissions: Browser.permissions.Permissions = { permissions: ['cookies'], origins: originPatterns(site) };
        // Asked on this click and dropped again afterwards: the extension never keeps cookie access.
        if (!(await browser.permissions.request(permissions))) {
          setStatus('error', `To sign in, allow the extension to read your ${site.label} sign-in. It asks each time and keeps no access.`);
          return;
        }
        signinButton.disabled = true;
        try {
          const cookies = await siteCookies(tabId, site.cookieDomains);
          if (cookies.length === 0) {
            setStatus('error', `You aren’t signed in to ${site.label} here. Sign in to ${site.label} in this tab first.`);
            return;
          }
          const reply = await ask(signinMessage(site.key, cookies));
          setStatus(reply.ok ? 'ok' : 'error', reply.ok ? `${site.label} is signed in to the app.` : reply.message ?? NOT_INSTALLED);
        } finally {
          await browser.permissions.remove(permissions).catch(() => false);
          signinButton.disabled = false;
        }
      },
    },
  });
  signinButton.append(icon('key'), h('span', { text: site ? `Sign ${site.label} in to the app` : 'Sign this site in to the app' }));

  const tip =
    site?.key === 'youtube'
      ? 'For YouTube, sign in from a private window, send the sign-in, then close that window, so browsing YouTube later doesn’t end the app’s sign-in. Allow the extension in private windows first.'
      : 'The app keeps the sign-in encrypted on this PC and uses it only for this site’s downloads.';

  app.replaceChildren(
    h(
      'header',
      { class: 'header' },
      h('img', { attrs: { src: '/icon/32.png', alt: '' } }),
      h(
        'div',
        { class: 'titles' },
        h('h1', { text: 'gfgRoyal Media Downloader' }),
        h('div', { class: 'site', text: host ?? 'Not available on this page' }),
      ),
    ),
    status,
    h(
      'section',
      { class: 'card actions' },
      downloadButton,
      signinButton,
      h('p', { class: 'field-hint', text: tip }),
    ),
  );
  app.removeAttribute('aria-busy');

  if (!host) {
    setStatus('info', 'Open a page with a video, playlist, or channel.');
    return;
  }
  const reply = await ask({ type: 'ping' });
  setStatus(reply.ok ? 'ok' : 'error', reply.ok ? `Connected to the app (version ${reply.version ?? ''}).` : reply.message ?? NOT_INSTALLED);
}

void main();
