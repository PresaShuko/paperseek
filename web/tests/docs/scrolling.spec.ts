// Against the documentation dev/preview server:
// PAPERSEEK_BROWSER_BASE_URL=... playwright test --config playwright.docs.config.ts scrolling.spec.ts
import { expect, test } from '@playwright/test';

test.use({ viewport: { width: 1440, height: 900 } });

test.beforeEach(async ({ page }) => {
  // Exercise the built-in still-image fallback: software-rendered WebGL on CI
  // can monopolize the renderer, unrelated to the wheel/navigation contract.
  await page.route('**/hero-painting.html?**', route => route.abort());
});

for (const prefix of ['/', '/zh/']) {
  test(`home sections turn one page per scroll and ignore stray trackpad input (${prefix})`, async ({ page }) => {
    await page.goto(prefix);
    await expect(page.locator('.ps-home')).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await page.mouse.move(700, 780);
    await expect.poll(() => page.evaluate(() => scrollY)).toBe(0);
    const second = await page.evaluate(() => {
      const nav = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--vp-nav-height')) || 64;
      return Math.round(document.querySelector('.ps-feature')!.getBoundingClientRect().top + scrollY - nav);
    });

    // Resting fingers and the end of momentum send sparse 1–3 px events; they never turn a page.
    for (const delta of [1, 2, 1, 3]) {
      await page.mouse.wheel(0, delta);
      await page.waitForTimeout(400);
    }
    await page.waitForTimeout(800);
    expect(await page.evaluate(() => scrollY)).toBe(0);

    // A deliberate scroll moves exactly one section.
    await page.mouse.wheel(0, 120);
    await page.waitForTimeout(1500);
    expect(Math.abs(await page.evaluate(() => scrollY) - second)).toBeLessThanOrEqual(2);

    // The momentum tail after that move stays on the same section.
    for (const delta of [3, 2, 1]) {
      await page.mouse.wheel(0, delta);
      await page.waitForTimeout(250);
    }
    await page.waitForTimeout(1200);
    expect(Math.abs(await page.evaluate(() => scrollY) - second)).toBeLessThanOrEqual(2);

    await page.mouse.wheel(0, -120);
    await page.waitForTimeout(1500);
    expect(await page.evaluate(() => scrollY)).toBe(0);
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
