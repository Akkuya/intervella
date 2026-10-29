import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mockAPI, schedule, room, meta } from './fixtures.ts'

test.beforeEach(async ({ page }) => {
  await mockAPI(page)
})

test('on-page room back link preserves the selected building calendar day', async ({ page }) => {
  await page.goto('/?view=buildings&building=SYN-A&schedule_date=2026-10-15')
  await page.getByRole('link', { name: 'SYN-A-101', exact: true }).click()
  await page.getByRole('link', { name: /Back to/ }).click()
  await expect(page).toHaveURL(/schedule_date=2026-10-15/)
  await expect(page.getByLabel('Schedule date')).toHaveValue('2026-10-15')
})

test('building controls preserve focus during consecutive keyboard date changes', async ({
  page,
}) => {
  await page.goto('/?view=buildings&building=SYN-A&schedule_date=2026-10-14')
  const next = page.getByRole('button', { name: 'Next day', exact: true })
  await next.focus()
  await page.keyboard.press('Enter')
  await expect(next).toBeFocused()
  await expect(page.getByLabel('Schedule date')).toHaveValue('2026-10-15')
  await page.keyboard.press('Enter')
  await expect(page.getByLabel('Schedule date')).toHaveValue('2026-10-16')
  const building = page.getByRole('combobox', { name: 'Building', exact: true })
  await building.focus()
  await building.selectOption('SYN-B')
  await expect(building).toBeFocused()
})

test('room timeline, scheduled event toggle, interval details and date navigation', async ({
  page,
}, testInfo) => {
  await page.goto('/?room=1&schedule_date=2026-10-14')
  await expect(page.getByRole('region', { name: 'Day calendar' })).toBeVisible()
  await expect(page.getByLabel('Show scheduled events')).toBeChecked()
  const event = page.getByRole('button', { name: /Scheduled event.*9:00 AM.*10:00 AM/ })
  await event.click()
  await expect(page.getByRole('dialog')).toContainText('Scheduled event')
  await page.keyboard.press('Escape')
  await expect(event).toBeFocused()
  await page.getByLabel('Show scheduled events').uncheck()
  await expect(page.locator('.event-block')).toHaveCount(0)
  await expect(page.locator('.calendar-period.scheduled')).toBeVisible()
  await page.reload()
  await expect(page.getByLabel('Show scheduled events')).not.toBeChecked()
  await page.getByLabel('Show scheduled events').check()
  await expect(page.getByRole('button', { name: /Cancelled event/ })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('room-calendar.png'), fullPage: true })
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
  await page.getByRole('button', { name: 'Next day', exact: true }).click()
  await expect(page).toHaveURL(/schedule_date=2026-10-15/)
})

test('building day uses one batch, aligned rows, unknown states and room deep links', async ({
  page,
}, testInfo) => {
  let batch = 0,
    individual = 0
  page.on('request', (request) => {
    if (request.url().includes('/buildings/SYN-A/schedule')) batch++
    if (/\/rooms\/\d+\/schedule/.test(request.url())) individual++
  })
  await page.goto('/?view=buildings&building=SYN-A&schedule_date=2026-10-14')
  await expect(page.getByRole('heading', { name: 'Building schedules', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'SYN-A-102', exact: true })).toBeVisible()
  await expect(page.locator('.calendar-period.unknown')).toBeVisible()
  expect(batch).toBe(1)
  expect(individual).toBe(0)
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
  await page.screenshot({ path: testInfo.outputPath('building-calendar.png'), fullPage: true })
  await page.getByRole('link', { name: 'SYN-A-101', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'SYN-A-101', exact: true })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Building schedules', exact: true })).toBeVisible()
})

test('calendar distinguishes repeated hours and preserves proportional intervals', async ({
  page,
}) => {
  const start = '2026-11-01T05:00:00Z',
    end = '2026-11-01T08:00:00Z'
  await page.route('**/api/v1/rooms/1/schedule*', (route) =>
    route.fulfill({
      json: {
        ...schedule,
        date: '2026-11-01',
        query: {
          start: '2026-11-01T04:00:00Z',
          end: '2026-11-02T05:00:00Z',
          timezone: 'America/Toronto',
        },
        data: [
          {
            id: 1,
            starts_at: '2026-11-01T05:30:00Z',
            ends_at: '2026-11-01T06:30:00Z',
            status: 'scheduled',
          },
        ],
        calendar: {
          window: { start, end, timezone: 'America/Toronto' },
          coverage: [{ starts_at: start, ends_at: end, completeness: 'complete' }],
          periods: [
            { starts_at: start, ends_at: '2026-11-01T05:30:00Z', state: 'available' },
            {
              starts_at: '2026-11-01T05:30:00Z',
              ends_at: '2026-11-01T06:30:00Z',
              state: 'scheduled',
            },
            { starts_at: '2026-11-01T06:30:00Z', ends_at: end, state: 'available' },
          ],
        },
      },
    }),
  )
  await page.goto('/?room=1&schedule_date=2026-11-01')
  const event = page.getByRole('button', { name: /Scheduled event.*1:30 AM EDT.*1:30 AM EST/ })
  await expect(event).toBeVisible()
  expect(await event.evaluate((node) => parseFloat((node as HTMLElement).style.width))).toBeCloseTo(
    100 / 3,
    3,
  )
})

test('67-room calendar remains one dark-theme batch with contained mobile scrolling', async ({
  page,
}, testInfo) => {
  let batch = 0,
    individual = 0
  await page.emulateMedia({ colorScheme: 'dark' })
  page.on('request', (request) => {
    if (request.url().includes('/buildings/SYN-A/schedule')) batch++
    if (/\/rooms\/\d+\//.test(request.url())) individual++
  })
  await page.route('**/api/v1/buildings/SYN-A/schedule*', (route) =>
    route.fulfill({
      json: {
        building: { id: 1, code: 'SYN-A', name: 'Synthetic Building A' },
        date: '2026-10-14',
        query: schedule.query,
        display_window: schedule.calendar!.window,
        meta: { ...meta, unknown_room_count: 0 },
        data: Array.from({ length: 67 }, (_, i) => ({
          room: { ...room, room_id: 100 + i, room_number: String(100 + i) },
          meetings: schedule.data,
          calendar: schedule.calendar,
        })),
      },
    }),
  )
  await page.goto('/?view=buildings&building=SYN-A&schedule_date=2026-10-14')
  await expect(page.locator('.calendar-room')).toHaveCount(67)
  await expect(page.locator('.now-line')).toHaveCount(67)
  expect(batch).toBe(1)
  expect(individual).toBe(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
  await page.locator('.calendar-scroll').evaluate((node) => node.scrollIntoView({ block: 'start' }))
  await page.screenshot({ path: testInfo.outputPath('calendar-scale-dark.png') })
})

test('building API failure and offline state do not show calendar availability', async ({
  page,
}) => {
  await page.route('**/api/v1/buildings/SYN-A/schedule*', (route) =>
    route.fulfill({ status: 503, json: { error: { code: 'database_unavailable' } } }),
  )
  await page.goto('/?view=buildings&building=SYN-A&schedule_date=2026-10-14')
  await expect(page.getByRole('alert')).toContainText('schedule service is unavailable')
  await expect(page.locator('.calendar-period')).toHaveCount(0)
  await page.context().setOffline(true)
  await expect(page.getByRole('heading', { name: 'You’re offline' })).toBeVisible()
})
