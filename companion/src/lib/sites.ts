/**
 * The sites the app knows (mirrors gfgmd/core/sites.py): which cookie domains
 * belong to each, so signing a site in sends only that site's cookies.
 */

export interface Site {
  key: string;
  label: string;
  hosts: string[];
  cookieDomains: string[];
}

export const SITES: Site[] = [
  { key: 'youtube', label: 'YouTube', hosts: ['youtube.com', 'youtu.be', 'youtube-nocookie.com'], cookieDomains: ['youtube.com', 'google.com'] },
  { key: 'instagram', label: 'Instagram', hosts: ['instagram.com'], cookieDomains: ['instagram.com'] },
  { key: 'facebook', label: 'Facebook', hosts: ['facebook.com', 'fb.watch', 'fb.com'], cookieDomains: ['facebook.com'] },
  { key: 'x', label: 'X (Twitter)', hosts: ['x.com', 'twitter.com', 't.co'], cookieDomains: ['x.com', 'twitter.com'] },
  { key: 'tiktok', label: 'TikTok', hosts: ['tiktok.com'], cookieDomains: ['tiktok.com'] },
  { key: 'snapchat', label: 'Snapchat', hosts: ['snapchat.com'], cookieDomains: ['snapchat.com'] },
  { key: 'pinterest', label: 'Pinterest', hosts: ['pinterest.com', 'pin.it'], cookieDomains: ['pinterest.com'] },
  { key: 'vimeo', label: 'Vimeo', hosts: ['vimeo.com'], cookieDomains: ['vimeo.com'] },
  { key: 'twitch', label: 'Twitch', hosts: ['twitch.tv'], cookieDomains: ['twitch.tv'] },
  { key: 'reddit', label: 'Reddit', hosts: ['reddit.com', 'redd.it'], cookieDomains: ['reddit.com'] },
  { key: 'dailymotion', label: 'Dailymotion', hosts: ['dailymotion.com', 'dai.ly'], cookieDomains: ['dailymotion.com'] },
  { key: 'soundcloud', label: 'SoundCloud', hosts: ['soundcloud.com'], cookieDomains: ['soundcloud.com'] },
];

/** The page's host name, or null for browser pages and other non-web URLs. */
export function hostFromUrl(url: string | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return null;
    return parsed.hostname.toLowerCase().replace(/\.$/, '') || null;
  } catch {
    return null;
  }
}

function matches(host: string, domain: string): boolean {
  return host === domain || host.endsWith(`.${domain}`);
}

/** The known site for a host, or a generic one named after the host without "www.". */
export function siteForHost(host: string): Site {
  const known = SITES.find((site) => site.hosts.some((domain) => matches(host, domain)));
  if (known) return known;
  const bare = host.replace(/^www\./, '');
  return { key: bare, label: bare, hosts: [bare], cookieDomains: [bare] };
}

/** The origin patterns to ask permission for when signing a site in. */
export function originPatterns(site: Site): string[] {
  return site.cookieDomains.flatMap((domain) => [`https://${domain}/*`, `https://*.${domain}/*`]);
}
