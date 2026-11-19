/**
 * Messages to the app's native host (com.gfgroyal.mediadownloader), matching
 * gfgmd/services/companion.py: ping, download, and signin.
 */

export const HOST_NAME = 'com.gfgroyal.mediadownloader';
export const MAX_URLS = 200;

export interface HostCookie {
  name: string;
  value: string;
  domain: string;
  path: string;
  secure: boolean;
  httpOnly: boolean;
  hostOnly: boolean;
  session: boolean;
  expirationDate?: number;
}

export type HostMessage =
  | { type: 'ping' }
  | { type: 'download'; urls: string[] }
  | { type: 'signin'; site: string; cookies: HostCookie[] };

export interface HostReply {
  ok: boolean;
  message?: string;
  app?: string;
  version?: string;
}

/** Web links only, without duplicates, at most MAX_URLS. */
export function downloadMessage(urls: string[]): HostMessage {
  const links = [...new Set(urls.filter((url) => /^https?:\/\//i.test(url)))].slice(0, MAX_URLS);
  return { type: 'download', urls: links };
}

/** Only the fields the app stores, for one site's cookies. */
export function signinMessage(site: string, cookies: chrome.cookies.Cookie[]): HostMessage {
  return {
    type: 'signin',
    site,
    cookies: cookies.map((cookie) => ({
      name: cookie.name,
      value: cookie.value,
      domain: cookie.domain,
      path: cookie.path,
      secure: cookie.secure,
      httpOnly: cookie.httpOnly,
      hostOnly: cookie.hostOnly,
      session: cookie.session,
      ...(cookie.expirationDate === undefined ? {} : { expirationDate: cookie.expirationDate }),
    })),
  };
}
