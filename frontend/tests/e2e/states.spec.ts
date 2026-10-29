import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { available, mockAPI, NOW, schedule, status } from './fixtures.ts'

test.beforeEach(async ({ page }) => {
  await mockAPI(page)
})

test('service connection failure is distinct from browser offline', async ({ page }) => {
  await page.route('**/api/v1/availability*', (route) => route.abort('failed'))
  await page.goto('/')
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
  await page.goto('/?room=999')
  await expect(page.getByText('This room could not be found.', { exact: false })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'SYN-A 101', exact: true })).not.toBeVisible()
})

test('switching from now to custom uses the current Toronto time', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('link', { name: 'View SYN-A 101' })).toBeVisible()
  await page.clock.fastForward(120_000)
  await page.getByLabel('Choose a time').check()
  await expect(page.getByLabel('Start time')).toHaveValue('08:02')
})

test('custom query restores URL and sends Toronto instant, duration and building', async ({
  page,
}) => {
  await page.goto('/?mode=custom&date=2026-10-14&time=10%3A30&duration=90&building=SYN-A')
  await expect(page.getByLabel('Choose a time')).toBeChecked()
  await expect(page.getByLabel('Start time')).toHaveValue('10:30')
  await expect(page.getByLabel('Duration')).toHaveValue('90')
  const request = page.waitForRequest(
    (item) =>
      item.url().includes('/availability') &&
      new URL(item.url()).searchParams.get('duration_minutes') === '30',
  )
  await page.getByLabel('Duration').selectOption('30')
  await page.getByRole('button', { name: 'Find rooms' }).click()
  const params = new URL((await request).url()).searchParams
  expect(params.get('start')).toBe('2026-10-14T14:30:00.000Z')
  expect(params.get('building')).toBe('SYN-A')
  await expect(page).toHaveURL(/duration=30/)
  await page.reload()
  await expect(page.getByLabel('Duration')).toHaveValue('30')
})

test('loading is distinct from no matching rooms', async ({ page }) => {
  let release = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/v1/availability*', async (route) => {
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
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Checking the schedule…' })).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'No matching rooms for this time' }),
  ).not.toBeVisible()
  release()
  await expect(page.getByRole('heading', { name: 'No matching rooms for this time' })).toBeVisible()
})

test('newer stale result is not masked by an older fresh status response', async ({ page }) => {
  await page.route('**/api/v1/availability*', (route) =>
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
  await page.goto('/')
  await expect(page.getByText('Older schedule', { exact: true })).toBeVisible()
  await expect(page.getByText('Stale source', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'View SYN-A 101' })).toBeVisible()
})

test('coverage error does not become empty or available rooms and server details are safe', async ({
  page,
}) => {
  await page.route('**/api/v1/availability*', (route) =>
    route.fulfill({
      status: 503,
      json: { error: { code: 'coverage_unavailable', message: 'SQL password=private' } },
      headers: { 'x-request-id': 'test-reference' },
    }),
  )
  await page.goto('/')
  await expect(page.getByText('Coverage is incomplete or unknown', { exact: false })).toBeVisible()
  await expect(page.getByRole('link', { name: 'View SYN-A 101' })).not.toBeVisible()
  await expect(page.getByText('No matching rooms for this time')).not.toBeVisible()
  await expect(page.getByText('test-reference', { exact: true })).toBeVisible()
  await expect(page.getByText('password=private', { exact: false })).not.toBeVisible()
})

test('offline state hides previous availability and reconnect recovers', async ({
  page,
  context,
}) => {
  await page.goto('/')
  await expect(page.getByRole('link', { name: 'View SYN-A 101' })).toBeVisible()
  await context.setOffline(true)
  await expect(page.getByRole('heading', { name: 'You’re offline' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'View SYN-A 101' })).not.toBeVisible()
  await context.setOffline(false)
  await expect(page.getByRole('link', { name: 'View SYN-A 101' })).toBeVisible()
})

test('superseded responses cannot replace a newer search', async ({ page }) => {
  let release = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/v1/availability*', async (route) => {
    if (new URL(route.request().url()).searchParams.get('building') !== 'SYN-B') {
      await gate
      await route.fulfill({ json: available }).catch(() => {})
    } else await route.fulfill({ json: { ...available, data: [available.data[1]] } })
  })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Checking the schedule…' })).toBeVisible()
  await expect(page.getByLabel('Building').locator('option[value="SYN-B"]')).toBeAttached()
  await page.getByLabel('Building').selectOption('SYN-B')
  await page.getByRole('button', { name: 'Find rooms' }).click()
  await expect(page.getByRole('link', { name: 'View SYN-B 205' })).toBeVisible()
  release()
  await page.waitForLoadState('networkidle')
  await expect(page.getByRole('link', { name: 'View SYN-A 101' })).not.toBeVisible()
})

test('DST gap is rejected and repeated time requires explicit offset', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('link', { name: 'View SYN-A 101' })).toBeVisible()
  await page.getByLabel('Choose a time').check()
  await page.getByLabel('Date', { exact: true }).fill('2026-03-08')
  await page.getByLabel('Start time').fill('02:30')
  await page.getByRole('button', { name: 'Find rooms' }).click()
  await expect(page.getByText('This time does not exist', { exact: false })).toBeVisible()
  await page.getByLabel('Date', { exact: true }).fill('2026-11-01')
  await page.getByLabel('Start time').fill('01:30')
  await page.getByRole('button', { name: 'Find rooms' }).click()
  await expect(page.getByText('This time occurs twice', { exact: false })).toBeVisible()
  await page.getByLabel('Time occurrence').selectOption('-05:00')
  const request = page.waitForRequest(
    (item) =>
      item.url().includes('/availability') &&
      new URL(item.url()).searchParams.get('start') === '2026-11-01T06:30:00.000Z',
  )
  await page.getByRole('button', { name: 'Find rooms' }).click()
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
        meta: {
          ...schedule.meta,
          coverage: { completeness: 'unknown', starts_at: null, ends_at: null },
        },
      },
    }),
  )
  await page.goto('/?mode=custom&date=2026-10-14&time=08%3A00&room=1')
  await expect(page.getByRole('heading', { name: 'No meetings listed' })).toBeVisible()
  await expect(
    page.getByText('Do not assume this room is available.', { exact: false }),
  ).toBeVisible()
  await expect(page.getByText('Coverage is unknown.', { exact: false })).toBeVisible()
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
  await page.getByRole('button', { name: 'Find rooms' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('link', { name: 'View SYN-A 101' })).toBeVisible()
  await page.getByRole('link', { name: 'View SYN-A 101' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'SYN-A 101', exact: true })).toBeFocused()
})

test('Now refreshes at 60 seconds while a fixed search waits for dataset change', async ({
  page,
}) => {
  await page.goto('/')
  await expect(page.getByRole('link', { name: 'View SYN-A 101' })).toBeVisible()
  const next = page.waitForRequest(
    (item) =>
      item.url().includes('/availability') &&
      Date.parse(new URL(item.url()).searchParams.get('start')!) >= Date.parse(NOW) + 60_000,
  )
  await page.clock.fastForward(60_000)
  await next
  let count = 0
  page.on('request', (item) => {
    if (item.url().includes('/availability')) count++
  })
  await page.goto('/?mode=custom&date=2026-10-14&time=09%3A00&duration=60')
  await expect(page.getByRole('link', { name: 'View SYN-A 101' })).toBeVisible()
  await page.waitForLoadState('networkidle')
  const before = count
  await page.clock.fastForward(60_000)
  await page.waitForLoadState('networkidle')
  expect(count).toBe(before)
  await page.route('**/api/v1/status', (route) =>
    route.fulfill({ json: { ...status, dataset_id: 'new-version' } }),
  )
  const changed = page.waitForRequest((item) => item.url().includes('/availability'))
  await page.clock.fastForward(60_000)
  await changed
})
