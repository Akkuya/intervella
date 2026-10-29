import { choose } from './control-helpers.ts'
import { test, expect } from '@playwright/test'
import { mockAPI, available, NOW } from './fixtures.ts'

test.beforeEach(async ({ page }) => {
  await mockAPI(page)
})

test('include-next collection stays neutral even when all returned rooms are available', async ({
  page,
}) => {
  await page.goto('/?include_next=1')
  await expect(page.getByRole('heading', { name: 'Room status', exact: true })).toBeVisible()
  await expect(page.locator('.result-count')).toContainText(
    '2 rooms shown: 2 available for the requested time',
  )
  await expect(page.locator('.room-card .badge.green')).toHaveCount(2)
})

for (const view of ['find', 'saved']) {
  test(`${view}: mixed room states use honest collection wording`, async ({ page }) => {
    await page.addInitScript(() =>
      localStorage.setItem(
        'utscvacant.favourites',
        JSON.stringify({ rooms: [1, 2, 3, 4], buildings: [] }),
      ),
    )
    await page.route('**/api/v1/room-search*', (route) =>
      route.fulfill({
        json: {
          ...available,
          data: (['available', 'scheduled', 'unknown', 'inactive'] as const).map(
            (state, index) => ({
              ...available.data[0],
              room_id: index + 1,
              room_number: String(101 + index),
              state,
              active: state !== 'inactive',
              available_until: state === 'available' ? available.data[0].available_until : null,
              next_available_start: state === 'inactive' || state === 'unknown' ? null : NOW,
            }),
          ),
          meta: { ...available.meta, unknown_room_count: 1 },
        },
      }),
    )
    await page.goto(view === 'find' ? '/?include_next=1' : '/?view=saved')
    await expect(page.getByRole('article')).toHaveCount(4)
    await expect(
      page.getByRole('heading', { name: 'Schedule available', exact: true }),
    ).not.toBeVisible()
    await expect(page.getByRole('heading', { name: 'Room status', exact: true })).toBeVisible()
    await expect(page.locator('.result-count')).toContainText('4 rooms shown')
    for (const text of [
      '1 available for the requested time',
      '1 with scheduled conflicts',
      '1 with unknown coverage',
      '1 inactive',
    ]) {
      await expect(page.locator('.result-count')).toContainText(text)
    }
    await expect(page.locator('.room-card .badge.green')).toHaveCount(1)
    for (const name of [
      'Schedule available',
      'Scheduled conflict',
      'Unknown coverage',
      'Inactive listing',
    ]) {
      await expect(page.locator('.room-card').getByText(name, { exact: true })).toBeVisible()
    }
  })

  for (const resume of [false, true]) {
    test(`${view}: until session ${resume ? 'expires while hidden' : 'ends and expires without invalid polls'}`, async ({
      page,
    }) => {
      await page.addInitScript(() =>
        localStorage.setItem(
          'utscvacant.favourites',
          JSON.stringify({ rooms: [1], buildings: [] }),
        ),
      )
      const requests: URLSearchParams[] = []
      await page.route('**/api/v1/room-search*', (route) => {
        const params = new URL(route.request().url()).searchParams
        requests.push(params)
        const start = params.get('start')!
        const end = params.get('end') ?? new Date(Date.parse(start) + 60 * 60_000).toISOString()
        return route.fulfill({
          json: {
            ...available,
            query: { ...available.query, start, end },
            data: [
              { ...available.data[0], available_until: '2026-10-15T02:00:00Z', next_booking: null },
            ],
          },
        })
      })
      await page.goto(`/?view=${view}&mode=now&end_date=2026-10-14&end_time=08%3A06`)
      await expect(page.getByRole('article')).toHaveCount(1)
      if (resume) {
        await page.evaluate(() =>
          Object.defineProperty(document, 'visibilityState', {
            value: 'hidden',
            configurable: true,
          }),
        )
        await page.clock.setSystemTime(new Date('2026-10-14T12:07:00Z'))
        await page.evaluate(() => {
          Object.defineProperty(document, 'visibilityState', {
            value: 'visible',
            configurable: true,
          })
          window.dispatchEvent(new Event('visibilitychange'))
        })
      } else {
        await page.clock.fastForward(61_000)
        await expect(
          page.getByRole('heading', { name: 'Session ending', exact: true }),
        ).toBeVisible()
        await expect(page.getByRole('article')).toHaveCount(0)
        const stopped = requests.length
        await page.clock.fastForward(5 * 60_000)
        expect(requests.length).toBe(stopped)
      }
      await expect(
        page.getByRole('heading', { name: 'Session expired', exact: true }),
      ).toBeVisible()
      await expect(page.getByRole('article')).toHaveCount(0)
      await expect(
        page.getByRole('heading', { name: 'Schedule available', exact: true }),
      ).not.toBeVisible()
      await expect(page.getByRole('heading', { name: 'Check this saved search' })).not.toBeVisible()
      await expect(
        page.getByRole('heading', { name: 'We couldn’t check the schedule' }),
      ).not.toBeVisible()
      for (const request of requests) {
        if (request.has('end'))
          expect(
            Date.parse(request.get('end')!) - Date.parse(request.get('start')!),
          ).toBeGreaterThanOrEqual(5 * 60_000)
      }
      await page.getByRole('link', { name: 'Find a room', exact: true }).click()
      await choose(page, 'Search length', 'duration')
      await page.getByRole('button', { name: 'Find rooms' }).click()
      await expect(page.getByRole('article')).toHaveCount(1)
      await expect(
        page.getByRole('heading', { name: 'Session expired', exact: true }),
      ).not.toBeVisible()
    })
  }
}
