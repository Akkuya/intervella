import { visit } from './control-helpers.ts'
import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mockAPI } from './fixtures.ts'
import { choose, finishClosing } from './control-helpers.ts'

test.beforeEach(async ({ page }) => {
  await mockAPI(page)
})

test('Intervella identity and saved preferences survive the rebrand', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('utscvacant.appearance', 'dark')
    localStorage.setItem('utscvacant.favourites', JSON.stringify({ rooms: [1], buildings: [] }))
  })
  await visit(page, '/')
  await expect(page).toHaveTitle('Intervella · Find your space between classes')
  await expect(page.locator('.brand')).toHaveText('Intervella')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expect(page.locator('meta[property="og:site_name"]')).toHaveAttribute(
    'content',
    'Intervella',
  )
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute('href', '/assets/intervella.svg')
  await expect(page.locator('body')).not.toContainText(/UTSCVacant|RoomFinder/)
  const saved = page.getByRole('button', { name: 'Remove SYN-A-101', exact: true })
  await expect(saved).toHaveAttribute('aria-pressed', 'true')
  const bounds = await saved.boundingBox()
  expect(bounds?.width).toBeLessThanOrEqual(48)
  expect(bounds?.height).toBeGreaterThanOrEqual(44)
  await saved.click()
  await expect(page.getByRole('button', { name: 'Save SYN-A-101', exact: true })).toHaveAttribute(
    'aria-pressed',
    'false',
  )
})

test('contextual building links preserve search filters and schedule date', async ({ page }) => {
  await visit(page, '/?mode=custom&date=2026-10-14&time=08%3A00&duration=60&building=SYN-A')
  await page.getByRole('link', { name: 'View SYN-A building schedule', exact: true }).click()
  await expect(page).toHaveURL(/view=buildings/)
  await expect(page).toHaveURL(/building=SYN-A/)
  await expect(page).toHaveURL(/duration=60/)
  await expect(page).toHaveURL(/schedule_date=2026-10-14/)
  await page.getByRole('link', { name: 'SYN-A-101', exact: true }).click()
  await page.getByRole('link', { name: 'View SYN-A building schedule', exact: true }).click()
  await expect(page).not.toHaveURL(/room=1/)
  await expect(page).toHaveURL(/schedule_date=2026-10-14/)
})

test('event visibility keeps the timeline stable and details centered', async ({ page }) => {
  await visit(page, '/?room=1&schedule_date=2026-10-14')
  const track = page.locator('.calendar-track')
  await expect(track).toBeVisible()
  const before = await track.boundingBox()
  await page.getByLabel('Show scheduled events').uncheck()
  expect((await track.boundingBox())?.height).toBe(before?.height)
  await page.getByLabel('Show scheduled events').check()
  const event = page.getByRole('button', { name: /Scheduled event.*9:00 AM.*10:00 AM/ })
  await event.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  const box = (await dialog.boundingBox())!
  const viewport = page.viewportSize()!
  expect(Math.abs(box.x + box.width / 2 - viewport.width / 2)).toBeLessThanOrEqual(2)
  expect(Math.abs(box.y + box.height / 2 - viewport.height / 2)).toBeLessThanOrEqual(2)
  await page.keyboard.press('Escape')
  await finishClosing(page)
  await expect(event).toBeFocused()
  await expect(page.getByRole('button', { name: 'Show schedule', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Refresh schedule', exact: true })).toBeVisible()
})

test('expanded filters remain in document flow and collapsed summary stays reachable', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1024, height: 650 })
  await visit(page, '/')
  await page.getByLabel('Choose a time', { exact: true }).check()
  await expect(page.getByRole('button', { name: 'Find rooms', exact: true })).toHaveCount(0)
  await page.locator('.search-filters summary').click()
  await page.locator('.search-column').scrollIntoViewIfNeeded()
  await expect(page.locator('.search-filters summary')).toBeInViewport()
})

for (const width of [360, 390, 430, 768, 1024, 1440]) {
  for (const theme of ['light', 'dark'] as const) {
    test(`audit student workflows at ${width}px in ${theme}`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 900 })
      await page.emulateMedia({ colorScheme: theme })
      await visit(page, '/')
      await expect(page.getByRole('link', { name: 'View SYN-A-101', exact: true })).toBeVisible()
      const noOverflow = async () =>
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
          true,
        )
      await noOverflow()
      await page.screenshot({
        path: info.outputPath(`search-${width}-${theme}.png`),
        fullPage: true,
        animations: 'disabled',
      })
      await page.getByLabel('Choose a time', { exact: true }).check()
      await page.getByRole('button', { name: /^Date: / }).click()
      await expect(
        page.getByRole('dialog', { name: 'Date calendar', exact: true }),
      ).toBeInViewport()
      await page.screenshot({
        path: info.outputPath(`date-${width}-${theme}.png`),
        animations: 'disabled',
      })
      await page.keyboard.press('Escape')
      await finishClosing(page)
      await page.getByRole('button', { name: /^Start time: / }).click()
      await expect(
        page.getByRole('dialog', { name: 'Start time picker', exact: true }),
      ).toBeInViewport()
      await page.screenshot({
        path: info.outputPath(`time-${width}-${theme}.png`),
        animations: 'disabled',
      })
      await page.keyboard.press('Escape')
      await finishClosing(page)
      await page.getByRole('link', { name: 'Building schedules', exact: true }).click()
      await expect(page.locator('.calendar-room')).toHaveCount(2)
      const previousDay = (await page
        .getByRole('button', { name: 'Previous day', exact: true })
        .boundingBox())!
      const nextDay = (await page
        .getByRole('button', { name: 'Next day', exact: true })
        .boundingBox())!
      expect(Math.abs(previousDay.y - nextDay.y)).toBeLessThanOrEqual(1)
      await noOverflow()
      await page.screenshot({
        path: info.outputPath(`building-${width}-${theme}.png`),
        fullPage: true,
        animations: 'disabled',
      })
      await page.getByRole('link', { name: 'SYN-A-101', exact: true }).click()
      await expect(page.getByRole('heading', { name: 'SYN-A-101', exact: true })).toBeVisible()
      await noOverflow()
      expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
      await page.screenshot({
        path: info.outputPath(`room-${width}-${theme}.png`),
        fullPage: true,
        animations: 'disabled',
      })
      await page.getByRole('button', { name: 'Save SYN-A-101', exact: true }).click()
      await page.getByRole('link', { name: 'Saved rooms', exact: true }).click()
      await expect(page.getByRole('link', { name: 'View SYN-A-101', exact: true })).toBeVisible()
      await noOverflow()
      await choose(page, 'Appearance', theme)
    })
  }
}
