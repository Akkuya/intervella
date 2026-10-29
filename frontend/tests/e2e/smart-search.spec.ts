import { choose, setTime } from './control-helpers.ts'
import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mockAPI, available, meta } from './fixtures.ts'

test.beforeEach(async ({ page }) => {
  await mockAPI(page)
})

test('expired until searches leave room and building calendar navigation usable', async ({
  page,
}) => {
  await page.goto('/?mode=now&end_date=2026-10-14&end_time=08%3A10&room=1&schedule_date=2026-10-14')
  await expect(page.getByRole('heading', { name: 'SYN-A-101', exact: true })).toBeVisible()
  await page.clock.fastForward(6 * 60_000)
  await expect(page.getByRole('heading', { name: 'SYN-A-101', exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Building schedules', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Day calendar' })).toBeVisible()
  await page.getByRole('button', { name: 'Next day', exact: true }).click()
  await expect(
    page.getByRole('button', { name: /^Schedule date: / }).locator('time'),
  ).toHaveAttribute('datetime', '2026-10-15')
})

test('saved now results refresh on visibility return after a booking boundary', async ({
  page,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem('utscvacant.favourites', JSON.stringify({ rooms: [1], buildings: [] })),
  )
  await page.goto('/?view=saved')
  await expect(page.getByRole('article', { name: 'SYN-A-101' })).toContainText('Schedule available')
  await page.evaluate(() =>
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true }),
  )
  await page.clock.setSystemTime(new Date('2026-10-14T13:05:00Z'))
  await page.route('**/api/v1/room-search*', (route) =>
    route.fulfill({
      json: {
        ...available,
        data: [
          {
            ...available.data[0],
            state: 'scheduled',
            available_until: null,
            next_available_start: '2026-10-14T14:00:00Z',
          },
        ],
      },
    }),
  )
  const refreshed = page.waitForRequest(
    (item) =>
      item.url().includes('/room-search') &&
      Date.parse(new URL(item.url()).searchParams.get('start')!) >=
        Date.parse('2026-10-14T13:05:00Z'),
    { timeout: 2500 },
  )
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
    window.dispatchEvent(new Event('visibilitychange'))
  })
  await refreshed
  await expect(page.getByRole('article', { name: 'SYN-A-101' })).toContainText('Scheduled conflict')
})

test('until, normalized name and sorting are shared in URLs and checked by the API', async ({
  page,
}, testInfo) => {
  await page.goto('/?mode=custom&date=2026-10-14&time=08%3A00')
  await choose(page, 'Search length', 'until')
  await setTime(page, 'Available until', '09:00')
  await page.getByRole('searchbox', { name: 'Room name' }).fill('SYNA101')
  await choose(page, 'Sort rooms', 'duration')
  const request = page.waitForRequest(
    (item) => item.url().includes('/room-search') && new URL(item.url()).searchParams.has('end'),
  )
  await page.getByRole('button', { name: 'Find rooms' }).click()
  const params = new URL((await request).url()).searchParams
  expect(params.get('start')).toBe('2026-10-14T12:00:00.000Z')
  expect(params.get('end')).toBe('2026-10-14T13:00:00.000Z')
  expect(params.has('duration_minutes')).toBe(false)
  expect(params.get('room_name')).toBe('SYNA101')
  expect(params.get('sort')).toBe('duration')
  await expect(page).toHaveURL(/end_time=09%3A00/)
  await page.reload()
  await expect(
    page.getByRole('button', { name: /^Available until: / }).locator('time'),
  ).toHaveAttribute('datetime', '09:00')
  await expect(page.getByRole('searchbox', { name: 'Room name' })).toHaveValue('SYNA101')
  await expect(page.getByRole('article', { name: 'SYN-A-101' })).toContainText(
    'Available until9:00 AM',
  )
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
  await page.screenshot({ path: testInfo.outputPath('smart-search.png'), fullPage: true })
})

test('next known openings and unknown coverage do not claim current availability', async ({
  page,
}) => {
  await page.route('**/api/v1/room-search*', (route) =>
    route.fulfill({
      json: {
        ...available,
        data: [
          {
            ...available.data[0],
            state: 'scheduled',
            available_until: null,
            next_available_start: '2026-10-14T14:00:00Z',
          },
          {
            ...available.data[1],
            state: 'unknown',
            available_until: null,
            next_available_start: null,
          },
        ],
      },
    }),
  )
  await page.goto('/?include_next=1')
  await expect(page.getByLabel('Include other rooms and next known openings')).toBeChecked()
  await expect(page.getByRole('article', { name: 'SYN-A-101' })).toContainText(
    'Next known opening10:00 AM',
  )
  await expect(page.getByRole('article', { name: 'SYN-B-205' })).toContainText('Unknown coverage')
  await expect(page.getByText('No suitable time confirmed')).toBeVisible()
  await expect(page.locator('.room-card .badge.green')).toHaveCount(0)
})

test('room and building favourites persist, batch checks and removal stay local', async ({
  page,
}, testInfo) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Save SYN-A-101', exact: true }).click()
  await page.getByRole('button', { name: 'Save SYN-B-205', exact: true }).click()
  await page.getByRole('link', { name: 'Building schedules', exact: true }).click()
  await page.getByRole('button', { name: 'Save SYN-A', exact: true }).click()
  let batches = 0,
    individuals = 0
  page.on('request', (item) => {
    const url = new URL(item.url())
    if (url.pathname.endsWith('/room-search') && url.searchParams.has('room_ids')) batches++
    if (url.pathname.includes('/rooms/')) individuals++
  })
  await page.getByRole('link', { name: 'Saved rooms', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Saved rooms', exact: true })).toBeFocused()
  await expect(page.getByRole('link', { name: 'View SYN-B-205' })).toBeVisible()
  expect(batches).toBe(1)
  expect(individuals).toBe(0)
  await expect(page.getByRole('link', { name: 'SYN-A · Synthetic Building A' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('button', { name: 'Remove SYN-A-101', exact: true })).toBeVisible()
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
  await page.screenshot({ path: testInfo.outputPath('saved-rooms.png'), fullPage: true })
  const stored = await page.evaluate(() =>
    JSON.parse(localStorage.getItem('utscvacant.favourites')!),
  )
  expect(stored).toEqual({ rooms: [1, 2], buildings: ['SYN-A'] })
  await page.getByRole('button', { name: 'Remove SYN-A-101', exact: true }).click()
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).not.toBeVisible()
  await page.getByRole('button', { name: 'Remove SYN-B-205', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'No saved rooms yet' })).toBeVisible()
})

test('blocked storage still permits session favourites', async ({ page }) => {
  await page.addInitScript(() => {
    Storage.prototype.getItem = () => {
      throw new Error('blocked')
    }
    Storage.prototype.setItem = () => {
      throw new Error('blocked')
    }
  })
  await page.goto('/?room=1')
  await page.getByRole('button', { name: 'Save SYN-A-101', exact: true }).click()
  await page.getByRole('link', { name: 'Saved rooms', exact: true }).click()
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).toBeVisible()
  await expect(
    page.getByText('If storage is blocked, favourites last for this session.', { exact: false }),
  ).toBeVisible()
})

test('saved inactive and missing listings, stale source, offline and API failures are explicit', async ({
  page,
  context,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem(
      'utscvacant.favourites',
      JSON.stringify({ rooms: [1, 999], buildings: [] }),
    ),
  )
  await page.route('**/api/v1/room-search*', (route) =>
    route.fulfill({
      json: {
        ...available,
        data: [
          {
            ...available.data[0],
            active: false,
            state: 'inactive',
            available_until: null,
            next_available_start: null,
          },
        ],
        meta: { ...available.meta, ...meta, freshness: 'stale', missing_room_ids: [999] },
      },
    }),
  )
  await page.goto('/?view=saved')
  await expect(page.getByText('Inactive listing', { exact: true })).toBeVisible()
  await expect(page.getByText('Older schedule', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Remove room 999' })).toBeVisible()
  await expect(page.locator('.room-card .badge.green')).toHaveCount(0)
  await context.setOffline(true)
  await expect(page.getByRole('heading', { name: 'You’re offline' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).not.toBeVisible()
  await context.setOffline(false)
  await page.waitForLoadState('networkidle')
  await expect(page.getByRole('button', { name: 'Refresh saved rooms' })).toBeEnabled()
  await page.route('**/api/v1/room-search*', (route) =>
    route.fulfill({ status: 503, json: { error: { code: 'database_unavailable' } } }),
  )
  await page.getByRole('button', { name: 'Refresh saved rooms' }).click()
  await expect(
    page.getByText('The schedule service is unavailable.', { exact: false }),
  ).toBeVisible()
})

test('until end time rejects DST gaps and demands an explicit repeated occurrence', async ({
  page,
}) => {
  await page.goto('/?mode=custom&date=2026-11-01&time=01%3A00&offset=-04%3A00')
  await choose(page, 'Search length', 'until')
  await setTime(page, 'Available until', '01:30')
  await page.getByRole('button', { name: 'Find rooms' }).click()
  await expect(page.getByText('This time occurs twice', { exact: false })).toBeVisible()
  await choose(page, 'End time occurrence', '-05:00')
  const request = page.waitForRequest(
    (item) =>
      item.url().includes('/room-search') &&
      new URL(item.url()).searchParams.get('end') === '2026-11-01T06:30:00.000Z',
  )
  await page.getByRole('button', { name: 'Find rooms' }).click()
  await request
  await page.goto('/?mode=custom&date=2026-03-08&time=01%3A30&end_date=2026-03-08&end_time=02%3A30')
  await expect(page.getByText('This time does not exist', { exact: false })).toBeVisible()
})

test('67 search cards render within mobile width without request fanout', async ({ page }) => {
  await page.route('**/api/v1/room-search*', (route) =>
    route.fulfill({
      json: {
        ...available,
        data: Array.from({ length: 67 }, (_, index) => ({
          ...available.data[1],
          room_id: index + 1,
          building_code: `SYN-${index % 10}`,
          room_number: String(100 + index),
        })),
      },
    }),
  )
  await page.goto('/')
  await expect(page.getByRole('article')).toHaveCount(67)
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(
    false,
  )
  await expect(page.locator('.booking').getByText('Available until', { exact: true })).toHaveCount(
    67,
  )
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
})
