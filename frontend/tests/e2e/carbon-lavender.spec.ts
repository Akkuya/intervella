import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { available, mockAPI } from './fixtures.ts'
import { choose } from './control-helpers.ts'

test.beforeEach(async ({ page }) => {
  await mockAPI(page)
})

test('reactive search debounces names, preserves focus, and never submits invalid intervals', async ({
  page,
}) => {
  const requests: string[] = []
  page.on('request', (request) => {
    if (request.url().includes('/room-search')) requests.push(request.url())
  })
  await page.goto('/?mode=custom&date=2026-10-14&time=08%3A00')
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Find rooms', exact: true })).toHaveCount(0)
  await page.locator('.search-filters summary').click()
  await choose(page, 'Building', 'SYN-A')
  await expect(page).toHaveURL(/building=SYN-A/)
  const field = page.getByRole('searchbox', { name: 'Room name' })
  const before = requests.length
  await field.fill('SY')
  await field.fill('SYNA101')
  await expect(page.getByRole('heading', { name: 'Updating your search' })).toBeVisible()
  await expect(page).toHaveURL(/room_name=SYNA101/)
  await expect(field).toBeFocused()
  await expect.poll(() => requests.length).toBe(before + 1)
  await choose(page, 'Search length', 'until')
  await expect(page.locator('.form-error')).not.toBeEmpty()
  await expect(page.getByRole('article')).toHaveCount(0)
  const invalidCount = requests.length
  await page.clock.fastForward(60_000)
  expect(requests.length).toBe(invalidCount)
})

for (const width of [360, 390, 430, 768, 1024, 1440]) {
  for (const theme of ['light', 'dark'] as const) {
    test(`Carbon Lavender compact search ${width} ${theme}`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 900 })
      await page.emulateMedia({ colorScheme: theme })
      await page.goto('/')
      await expect(page.getByRole('link', { name: 'View SYN-A-101' })).toBeVisible()
      const colors = await page.locator('html').evaluate((el) => ({
        canvas: getComputedStyle(el).getPropertyValue('--canvas').trim(),
        accent: getComputedStyle(el).getPropertyValue('--accent').trim(),
      }))
      expect(colors.canvas).toBe(theme === 'dark' ? '#15171b' : '#f7f7fa')
      expect(colors.accent).toBe(theme === 'dark' ? '#b6a3ff' : '#6650b8')
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
      await page.screenshot({ path: info.outputPath('compact-search.png'), fullPage: true })
      await page.locator('.search-filters summary').click()
      await page.screenshot({ path: info.outputPath('open-filters.png'), fullPage: true })
    })
  }
}

test('one Now label describes all calendar continuation lines', async ({ page }, info) => {
  await page.goto('/?view=buildings&building=SYN-A&schedule_date=2026-10-14')
  await expect(page.locator('.now-marker')).toHaveCount(1)
  await expect(page.locator('.now-marker')).toHaveAccessibleName(/Current Toronto time/)
  expect(await page.locator('.now-line').count()).toBeGreaterThan(0)
  await expect(page.locator('.now-line').first()).toHaveAttribute('aria-hidden', 'true')
  await page.screenshot({ path: info.outputPath('building-now.png'), fullPage: true })
})

test('reflow and forced colors retain keyboard filters and reduced motion', async ({ page }) => {
  await page.setViewportSize({ width: 720, height: 900 })
  await page.emulateMedia({ reducedMotion: 'reduce', forcedColors: 'active' })
  await page.goto('/')
  await page.locator('body').evaluate((el) => {
    el.style.zoom = '2'
  })
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  const summary = page.locator('.search-filters summary')
  await summary.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByLabel('Free now', { exact: true })).toBeVisible()
  await expect(summary).toBeFocused()
})

for (const width of [360, 1440])
  for (const theme of ['light', 'dark'] as const) {
    test(`review state and interval renders ${width} ${theme}`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 900 })
      await page.emulateMedia({ colorScheme: theme })
      let state = 'empty'
      await page.route('**/api/v1/room-search*', (route) =>
        route.fulfill({
          json: {
            ...available,
            data:
              state === 'empty'
                ? []
                : state === 'unknown'
                  ? [
                      {
                        ...available.data[0],
                        state: 'unknown',
                        available_until: null,
                        next_available_start: null,
                      },
                    ]
                  : available.data,
            meta: {
              ...available.meta,
              freshness: state === 'stale' ? 'stale' : 'fresh',
              generated_at: '2026-10-14T12:00:01Z',
              unknown_room_count: state === 'unknown' ? 1 : 0,
            },
          },
        }),
      )
      for (const scenario of ['empty', 'unknown', 'stale']) {
        state = scenario
        await page.goto('/?include_next=1')
        if (scenario === 'empty')
          await expect(
            page.getByRole('heading', { name: 'No room listings to show' }),
          ).toBeVisible()
        else if (scenario === 'unknown')
          await expect(page.getByRole('article')).toContainText('Unknown coverage')
        else await expect(page.getByText('Older schedule', { exact: true })).toBeVisible()
        expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
        await page.screenshot({ path: info.outputPath(`${scenario}.png`), fullPage: true })
      }
      await page.goto('/?room=1&schedule_date=2026-10-14')
      const booking = page.getByRole('button', { name: /Scheduled event.*9:00 AM.*10:00 AM/ })
      await booking.click()
      await expect(page.getByRole('dialog')).toContainText('60 minutes')
      await page.screenshot({ path: info.outputPath('event-dialog.png') })
      await page.keyboard.press('Escape')
      await expect(booking).toBeFocused()
    })
  }
