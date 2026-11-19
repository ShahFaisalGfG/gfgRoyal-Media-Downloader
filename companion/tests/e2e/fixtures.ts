/// <reference types="chrome" />
import { resolve } from 'node:path';
import { type BrowserContext, type Worker, test as base, chromium, expect } from '@playwright/test';

const EXTENSION_PATH = resolve('.output/chrome-mv3');

interface Fixtures {
  context: BrowserContext;
  worker: Worker;
  extensionId: string;
}

export const test = base.extend<Fixtures>({
  // Branded Chrome ignores --load-extension, so tests use Playwright's bundled Chromium.
  // eslint-disable-next-line no-empty-pattern -- Playwright fixtures must destructure their dependencies.
  context: async ({}, use) => {
    const context = await chromium.launchPersistentContext('', {
      channel: 'chromium',
      headless: true,
      args: [`--disable-extensions-except=${EXTENSION_PATH}`, `--load-extension=${EXTENSION_PATH}`],
    });
    await use(context);
    await context.close();
  },
  worker: async ({ context }, use) => {
    const worker = context.serviceWorkers()[0] ?? (await context.waitForEvent('serviceworker'));
    await use(worker);
  },
  extensionId: async ({ worker }, use) => {
    await use(new URL(worker.url()).host);
  },
});

export { expect };
