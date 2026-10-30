import { visit } from './control-helpers.ts'
import { choose, selected, setTime, setDate, selectTrigger } from './control-helpers.ts'
import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { available, mockAPI, NOW, schedule, status } from './fixtures.ts'

test.beforeEach(async ({ page }) => {
  await mockAPI(page)
})

for (const url of ['/', '/?mode=custom&date=2026-10-14&time=09%3A00']) {
  test(`explicit unchanged search refetches while normalizing ${url}`, async ({ page }) => {
    let requests = 0
    page.on('request', (request) => {
      if (request.url().includes('/room-search')) requests++
    })
    await visit(page, url)
    await expect(page.getByRole('link', { name: 'View SYN-A-101' })).toBeVisible()
    await page.waitForLoadState('networkidle')
    const before = requests
    await page.getByRole('button', { name: 'Refresh', exact: true }).click()
    await expect.poll(() => requests, { timeout: 1500 }).toBeGreaterThan(before)
  })
}

test('search windows distinguish repeated times and overnight end dates', async ({
  page,
}, testInfo) => {
  let query = { ...available.query, start: '2026-11-01T05:30:00Z', end: '2026-11-01T06:30:00Z' }
  await page.route('**/api/v1/room-search*', (route) =>
    route.fulfill({
      json: {
        ...available,
        query,
        data: available.data.map((room) => ({
          ...room,
          available_until: query.end,
          next_available_start: query.start,
        })),
      },
    }),
  )
  await visit(page, '/?mode=custom&date=2026-11-01&time=01%3A30&offset=-04%3A00')
  await expect(page.locator('.time-strip')).toContainText('1:30 AM EDT')
  await expect(page.locator('.time-strip')).toContainText('1:30 AM EST')
  query = { ...query, start: '2026-10-15T03:30:00Z', end: '2026-10-15T04:30:00Z' }
  await visit(page, '/?mode=custom&date=2026-10-14&time=23%3A30')
  await expect(page.locator('.time-strip strong')).toContainText('Oct 15')
  await expect(page.locator('.time-strip strong')).toContainText('12:30 AM')
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(
    false,
  )
  await page.locator('.time-strip').screenshot({ path: testInfo.outputPath('overnight.png') })
})

test('service connection failure is distinct from browser offline', async ({ page }) => {
  await page.route('**/api/v1/room-search*', (route) => route.abort('failed'))
  await visit(page, '/')
  await expect(
    page.getByText('Could not reach the schedule service.', { exact: false }),
  ).toBeVisible()
  await expect(page.getByRole('heading', { name: 'You’re offline' })).not.toBeVisible()
})

test('unknown room shows safe not-found state without fabricated details', async ({ page }) => {
  // The generic schedule fixture still refers to room 1; it must never become room 999's details.
  await page.route('**/api/v1/rooms/999*', (route) =>
    route.fulfill({ status: 404, json: { error: { code: 'room_not_found' } } }),
  )
  await visit(page, '/?room=999')
  await expect(page.getByText('This room could not be found.', { exact: false })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'SYN-A-101', exact: true })).not.toBeVisible()
})

test('switching from now to custom initializes the nearest five-minute Toronto time', async ({
  page,
}) => {
  await visit(page, '/')
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).toBeVisible()
  await page.clock.fastForward(120_000)
  await page.getByLabel('Choose a time').check()
  await expect(page.getByRole('button', { name: /^Start time: / }).locator('time')).toHaveAttribute(
    'datetime',
    '08:00',
  )
})

test('custom query restores URL and sends Toronto instant, duration and building', async ({
  page,
}) => {
  await visit(page, '/?mode=custom&date=2026-10-14&time=10%3A30&duration=90&building=SYN-A')
  await expect(page.getByLabel('Choose a time')).toBeChecked()
  await expect(page.getByRole('button', { name: /^Start time: / }).locator('time')).toHaveAttribute(
    'datetime',
    '10:30',
  )
  await selected(page, 'Duration', '90')
  const request = page.waitForRequest(
    (item) =>
      item.url().includes('/room-search') &&
      new URL(item.url()).searchParams.get('duration_minutes') === '30',
  )
  await choose(page, 'Duration', '30')
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  const params = new URL((await request).url()).searchParams
  expect(params.get('start')).toBe('2026-10-14T14:30:00.000Z')
  expect(params.get('building')).toBe('SYN-A')
  await expect(page).toHaveURL(/duration=30/)
  await page.reload()
  await selected(page, 'Duration', '30')
})

test('loading is distinct from no matching rooms', async ({ page }) => {
  let release = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/v1/room-search*', async (route) => {
    await gate
    await route
      .fulfill({
        json: {
          ...available,
          data: [],
          meta: { ...available.meta, unknown_room_count: 0, coverage: 'complete' },
        },
      })
      .catch(() => {})
  })
  await visit(page, '/')
  await expect(page.getByRole('heading', { name: 'Checking the schedule…' })).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'No matching rooms for this time' }),
  ).not.toBeVisible()
  release()
  await expect(page.getByRole('heading', { name: 'No matching rooms for this time' })).toBeVisible()
})

test('newer stale result is not masked by an older fresh status response', async ({ page }) => {
  await page.route('**/api/v1/room-search*', (route) =>
    route.fulfill({
      json: {
        ...available,
        meta: {
          ...available.meta,
          freshness: 'stale',
          warnings: ['stale_dataset'],
          generated_at: '2026-10-14T12:00:01Z',
        },
      },
    }),
  )
  await visit(page, '/')
  await expect(page.getByText('Older schedule', { exact: true })).toBeVisible()
  await expect(page.getByText('Stale source', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).toBeVisible()
})

test('coverage error does not become empty or available rooms and server details are safe', async ({
  page,
}) => {
  await page.route('**/api/v1/room-search*', (route) =>
    route.fulfill({
      status: 503,
      json: { error: { code: 'coverage_unavailable', message: 'SQL password=private' } },
      headers: { 'x-request-id': 'test-reference' },
    }),
  )
  await visit(page, '/')
  await expect(page.getByText('Coverage is incomplete or unknown', { exact: false })).toBeVisible()
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).not.toBeVisible()
  await expect(page.getByText('No matching rooms for this time')).not.toBeVisible()
  await expect(page.getByText('test-reference', { exact: true })).toBeVisible()
  await expect(page.getByText('password=private', { exact: false })).not.toBeVisible()
})

test('offline state hides previous availability and reconnect recovers', async ({
  page,
  context,
}) => {
  await visit(page, '/')
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).toBeVisible()
  await context.setOffline(true)
  await expect(page.getByRole('heading', { name: 'You’re offline' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).not.toBeVisible()
  await context.setOffline(false)
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).toBeVisible()
})

test('superseded responses cannot replace a newer search', async ({ page }) => {
  let release = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/v1/room-search*', async (route) => {
    if (new URL(route.request().url()).searchParams.get('building') !== 'SYN-B') {
      await gate
      await route.fulfill({ json: available }).catch(() => {})
    } else await route.fulfill({ json: { ...available, data: [available.data[1]] } })
  })
  await visit(page, '/')
  await expect(page.getByRole('heading', { name: 'Checking the schedule…' })).toBeVisible()
  await expect(selectTrigger(page, 'Building')).toBeAttached()
  await choose(page, 'Building', 'SYN-B')
  await expect(page.getByRole('link', { name: 'View SYN-B-205' })).toBeVisible()
  release()
  await page.waitForLoadState('networkidle')
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).not.toBeVisible()
})

test('DST gap is rejected and repeated time requires explicit offset', async ({ page }) => {
  await visit(page, '/')
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).toBeVisible()
  await page.getByLabel('Choose a time').check()
  await setDate(page, 'Date', '2026-03-08')
  await page.getByRole('button', { name: /^Start time: / }).click()
  await page.getByLabel('Type a time').fill('02:30')
  await page.getByRole('button', { name: 'Use time', exact: true }).click()
  await expect(page.getByText('This time does not exist', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await setDate(page, 'Date', '2026-11-01')
  await setTime(page, 'Start time', '01:30')
  await expect(page.getByText('This time occurs twice', { exact: false })).toBeVisible()
  await choose(page, 'Time occurrence', '-05:00')
  const request = page.waitForRequest(
    (item) =>
      item.url().includes('/room-search') &&
      new URL(item.url()).searchParams.get('start') === '2026-11-01T06:30:00.000Z',
  )
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await request
  await expect(page).toHaveURL(/offset=-05%3A00/)
})

test('unknown room schedule never implies availability and remains accessible', async ({
  page,
}, testInfo) => {
  await page.route('**/api/v1/rooms/1/schedule*', (route) =>
    route.fulfill({
      json: {
        ...schedule,
        data: [],
        calendar: {
          window: schedule.calendar!.window,
          coverage: [],
          periods: [
            {
              starts_at: schedule.calendar!.window.start,
              ends_at: schedule.calendar!.window.end,
              state: 'unknown',
            },
          ],
        },
        meta: {
          ...schedule.meta,
          coverage: { completeness: 'unknown', starts_at: null, ends_at: null },
        },
      },
    }),
  )
  await visit(page, '/?mode=custom&date=2026-10-14&time=08%3A00&room=1')
  await expect(page.getByRole('heading', { name: 'No meetings listed' })).toBeVisible()
  await expect(
    page.getByText('Do not assume this room is available.', { exact: false }),
  ).toBeVisible()
  await expect(page.getByText('Coverage is unknown.', { exact: false })).toBeVisible()
  await expect(page.locator('.calendar-period.available')).toHaveCount(0)
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
  await page.screenshot({ path: testInfo.outputPath('room.png'), fullPage: true })
})

test('keyboard controls, focus restoration and malformed bookmark recovery', async ({ page }) => {
  await page.goto('/?duration=bad')
  await expect(page.getByRole('heading', { name: 'Check this saved search' })).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('main')).toBeFocused()
  await choose(page, 'Duration', '90')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).toBeVisible()
  await page.getByRole('link', { name: 'View SYN-A-101' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'SYN-A-101', exact: true })).toBeFocused()
})

test('Now refreshes at 60 seconds while a fixed search waits for dataset change', async ({
  page,
}) => {
  await visit(page, '/')
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).toBeVisible()
  const next = page.waitForRequest(
    (item) =>
      item.url().includes('/room-search') &&
      Date.parse(new URL(item.url()).searchParams.get('start')!) >= Date.parse(NOW) + 60_000,
  )
  await page.clock.fastForward(60_000)
  await next
  let count = 0
  page.on('request', (item) => {
    if (item.url().includes('/room-search')) count++
  })
  await visit(page, '/?mode=custom&date=2026-10-14&time=09%3A00&duration=60')
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).toBeVisible()
  await page.waitForLoadState('networkidle')
  const before = count
  await page.clock.fastForward(60_000)
  await page.waitForLoadState('networkidle')
  expect(count).toBe(before)
  await page.route('**/api/v1/status', (route) =>
    route.fulfill({ json: { ...status, dataset_id: 'new-version' } }),
  )
  const changed = page.waitForRequest((item) => item.url().includes('/room-search'))
  await page.clock.fastForward(60_000)
  await changed
})
