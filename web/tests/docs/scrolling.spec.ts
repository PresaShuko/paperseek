// Against the documentation dev/preview server:
// PAPERSEEK_BROWSER_BASE_URL=... playwright test --config playwright.docs.config.ts scrolling.spec.ts
import { expect, test } from '@playwright/test';

test.use({ viewport: { width: 1440, height: 900 } });

for (const prefix of ['/', '/zh/']) {
  test(`small wheel inputs do not advance home sections (${prefix})`, async ({ page }) => {
    await page.goto(prefix);
    await expect(page.locator('.ps-home')).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await page.mouse.move(700, 780);
    await expect.poll(() => page.evaluate(() => scrollY)).toBe(0);

    await page.mouse.wheel(0, 80);
    await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(0);
    // Let both native scrolling and any scripted section animation settle.
    await page.waitForTimeout(1200);
    const first = await page.evaluate(() => scrollY);
    expect(first).toBeLessThan(140);

    // A delayed, small trackpad tail must not become a new full-screen gesture.
    await page.mouse.wheel(0, 1);
    await page.waitForTimeout(1200);
    expect(Math.abs(await page.evaluate(() => scrollY) - first)).toBeLessThan(10);
    await page.mouse.wheel(0, -20);
    await page.waitForTimeout(600);
    expect(await page.evaluate(() => scrollY)).toBeLessThan(first);
    expect(new URL(page.url()).pathname).toBe(prefix);
  });

  test(`document scrolling and explicit outline links work after leaving home (${prefix})`, async ({ page }) => {
    await page.goto(prefix);
    await expect(page.locator('.ps-home')).toBeVisible();
    await page.locator(`.VPNavBarMenuLink[href="${prefix}get-started/"]`).click();
    await expect(page.locator('.vp-doc h1')).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await expect.poll(() => page.evaluate(() => scrollY)).toBe(0);
    const url = page.url();
    await page.mouse.move(800, 500);
    await page.mouse.wheel(0, 120);
    await page.waitForTimeout(1200);
    const y = await page.evaluate(() => scrollY);
    expect(y).toBeGreaterThan(60);
    expect(y).toBeLessThan(180);
    expect(page.url()).toBe(url);

    const link = page.locator('.VPDocAsideOutline a.outline-link').last();
    const hash = await link.getAttribute('href');
    await link.click();
    await expect.poll(() => decodeURIComponent(new URL(page.url()).hash)).toBe(decodeURIComponent(hash!));
    const heading = page.locator(`[id="${decodeURIComponent(hash!.slice(1))}"]`);
    await expect(heading).toBeInViewport();
    const before = await page.evaluate(() => scrollY);
    await page.waitForTimeout(1200);
    expect(Math.abs(await page.evaluate(() => scrollY) - before)).toBeLessThan(3);
  });
}
