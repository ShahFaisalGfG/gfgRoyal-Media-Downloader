/**
 * One-shot requests to the app's native messaging host. When the app isn't
 * installed (or its host isn't registered) the reply says so instead of
 * throwing, so the popup can explain what to do.
 */

import { browser } from 'wxt/browser';
import { HOST_NAME, type HostMessage, type HostReply } from './messages';

export const NOT_INSTALLED =
  'gfgRoyal Media Downloader isn’t installed, or its browser connection isn’t set up. Install the app, then try again.';

/** Sends one message and returns the host's reply. */
export async function ask(message: HostMessage): Promise<HostReply> {
  try {
    const reply = (await browser.runtime.sendNativeMessage(HOST_NAME, message)) as HostReply | undefined;
    return reply ?? { ok: false, message: NOT_INSTALLED };
  } catch (error) {
    console.debug('[gfgRoyal Media Downloader] Native host unavailable', error);
    return { ok: false, message: NOT_INSTALLED };
  }
}
