import { browser } from 'wxt/browser';
import { defineBackground } from 'wxt/utils/define-background';
import { ask } from '../lib/host';
import { downloadMessage } from '../lib/messages';

const MENU_LINK = 'download-link';
const MENU_PAGE = 'download-page';

/** Right-click entries: a link, a video, or the page itself. */
export default defineBackground(() => {
  browser.runtime.onInstalled.addListener(() => {
    void browser.contextMenus.removeAll().then(() => {
      browser.contextMenus.create({
        id: MENU_LINK,
        title: 'Download link with gfgRoyal Media Downloader',
        contexts: ['link'],
      });
      browser.contextMenus.create({
        id: MENU_PAGE,
        title: 'Download this page with gfgRoyal Media Downloader',
        contexts: ['page', 'video', 'audio', 'frame'],
      });
    });
  });

  browser.contextMenus.onClicked.addListener((info, tab) => {
    const url = info.menuItemId === MENU_LINK ? info.linkUrl : (info.frameUrl ?? info.pageUrl ?? tab?.url);
    if (!url) return;
    void ask(downloadMessage([url])).then((reply) => {
      if (!reply.ok) console.warn('[gfgRoyal Media Downloader]', reply.message);
    });
  });
});
