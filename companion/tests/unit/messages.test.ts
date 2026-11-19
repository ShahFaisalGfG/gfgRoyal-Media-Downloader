import { describe, expect, it } from 'vitest';
import { MAX_URLS, downloadMessage, signinMessage } from '../../src/lib/messages';

describe('downloadMessage', () => {
  it('keeps web links only, once each, within the limit', () => {
    const urls = ['https://a.example/1', 'javascript:alert(1)', 'https://a.example/1', 'http://b.example/2'];
    expect(downloadMessage(urls)).toEqual({ type: 'download', urls: ['https://a.example/1', 'http://b.example/2'] });
    const many = Array.from({ length: MAX_URLS + 5 }, (_, i) => `https://a.example/${i}`);
    const message = downloadMessage(many);
    expect(message.type === 'download' && message.urls.length).toBe(MAX_URLS);
  });
});

describe('signinMessage', () => {
  it('sends only the fields the app stores', () => {
    const cookie = {
      name: 'SAPISID',
      value: 'v',
      domain: '.youtube.com',
      path: '/',
      secure: true,
      httpOnly: false,
      hostOnly: false,
      session: false,
      expirationDate: 1999999999,
      sameSite: 'lax',
      storeId: '0',
    } as chrome.cookies.Cookie;
    const message = signinMessage('youtube', [cookie, { ...cookie, name: 'S', session: true, expirationDate: undefined }]);
    expect(message).toEqual({
      type: 'signin',
      site: 'youtube',
      cookies: [
        { name: 'SAPISID', value: 'v', domain: '.youtube.com', path: '/', secure: true, httpOnly: false, hostOnly: false, session: false, expirationDate: 1999999999 },
        { name: 'S', value: 'v', domain: '.youtube.com', path: '/', secure: true, httpOnly: false, hostOnly: false, session: true },
      ],
    });
  });
});
