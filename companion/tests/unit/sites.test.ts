import { describe, expect, it } from 'vitest';
import { hostFromUrl, originPatterns, siteForHost } from '../../src/lib/sites';

describe('hostFromUrl', () => {
  it('reads web pages only', () => {
    expect(hostFromUrl('https://WWW.YouTube.com/watch?v=x')).toBe('www.youtube.com');
    expect(hostFromUrl('http://example.org./a')).toBe('example.org');
    expect(hostFromUrl('chrome://extensions')).toBeNull();
    expect(hostFromUrl('file:///C:/a.html')).toBeNull();
    expect(hostFromUrl('not a url')).toBeNull();
    expect(hostFromUrl(undefined)).toBeNull();
  });
});

describe('siteForHost', () => {
  it('maps known sites and their subdomains to the app’s site keys', () => {
    expect(siteForHost('m.youtube.com').key).toBe('youtube');
    expect(siteForHost('music.youtube.com').cookieDomains).toEqual(['youtube.com', 'google.com']);
    expect(siteForHost('twitter.com').key).toBe('x');
    expect(siteForHost('www.instagram.com').label).toBe('Instagram');
    expect(siteForHost('vm.tiktok.com').key).toBe('tiktok');
    expect(siteForHost('t.co').key).toBe('x');
    expect(siteForHost('pin.it').key).toBe('pinterest');
    expect(siteForHost('www.snapchat.com').key).toBe('snapchat');
  });

  it('does not match look-alike hosts', () => {
    expect(siteForHost('notyoutube.com').key).toBe('notyoutube.com');
    expect(siteForHost('youtube.com.evil.example').key).toBe('youtube.com.evil.example');
  });

  it('names other sites after their host without www', () => {
    const site = siteForHost('www.media.example.org');
    expect(site).toMatchObject({ key: 'media.example.org', cookieDomains: ['media.example.org'] });
  });
});

describe('originPatterns', () => {
  it('asks only for the site’s own domains', () => {
    expect(originPatterns(siteForHost('youtube.com'))).toEqual([
      'https://youtube.com/*',
      'https://*.youtube.com/*',
      'https://google.com/*',
      'https://*.google.com/*',
    ]);
  });
});
