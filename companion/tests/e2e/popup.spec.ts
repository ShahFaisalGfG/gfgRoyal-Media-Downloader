import { expect, test } from './fixtures';

// The extension has no "tabs" permission: it reads the current tab's address only through
// activeTab, which the browser grants when the user clicks the toolbar button. A test can't click
// the toolbar, so the popup sees no address here; the address flow is covered by unit tests of
// lib/sites and by a manual check with the built extension.

test('the extension keeps its fixed ID', async ({ extensionId }) => {
  expect(extensionId).toBe('gipopofnfbdhmmkpeaffnjfkkdbnjepp');
});

test('without access to the page, the popup offers nothing and says why', async ({ context, worker, extensionId }) => {
  const page = await context.newPage();
  await page.goto('/video.html');
  const tabId = await worker.evaluate(async () => Math.max(...(await chrome.tabs.query({})).map((tab) => tab.id ?? 0)));

  const popup = await context.newPage();
  await popup.goto(`chrome-extension://${extensionId}/popup.html?tabId=${tabId}`);
  await expect(popup.locator('.site')).toHaveText('Not available on this page');
  await expect(popup.getByRole('status')).toContainText('Open a page with a video');
  await expect(popup.getByRole('button', { name: 'Download this page' })).toBeDisabled();
  await expect(popup.getByRole('button', { name: 'Sign this site in to the app' })).toBeDisabled();
});
