import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { choose, setDate } from './control-helpers.ts'

test.use({ baseURL: 'http://127.0.0.1:4174' })
const days = Array.from({ length: 7 }, (_, i) => `2026-11-0${i + 1}`)
const dataset = '11111111-1111-4111-8111-111111111111'
const health = {
  active: {
    dataset_id: dataset,
    published_at: '2026-10-29T12:00:00Z',
    imported_at: '2026-10-29T11:00:00Z',
    source_fetched_at: '2026-10-25T11:00:00Z',
    freshness: 'stale',
    source_format: 'weekly',
    parser_version: 'local-grid-v2',
    rooms: 2,
    buildings: 1,
    occurrences: 5,
    days: days.map((date) => ({
      date,
      fetched_at: '2026-10-25T11:00:00Z',
      freshness: 'stale',
      complete_rooms: 1,
      unknown_rooms: 1,
      missing_rooms: 0,
    })),
  },
  history: [
    {
      run_id: 'synthetic-run',
      status: 'succeeded',
      dataset_id: dataset,
      published_at: '2026-10-29T12:00:00Z',
      started_at: '2026-10-29T11:00:00Z',
      error_code: null,
      counts: {
        source_format: 'weekly',
        dates: days,
        rooms: 2,
        occurrences: 5,
        review_reason: 'synthetic-review',
      },
    },
  ],
}
const preview = {
  summary: {
    dates: days,
    rooms: 2,
    buildings: 1,
    occurrences: 5,
    unknown_rooms: 1,
    source_format: 'weekly',
    source_fetched_at: '2026-10-25T11:00:00Z',
    input_hash: 'a'.repeat(64),
  },
  sources: days.map((date) => ({ date, fetched_at: '2026-10-25T11:00:00Z' })),
  comparison: {
    baseline_dataset_id: dataset,
    added_rooms: ['SYN-A-102'],
    missing_rooms: [],
    capacity_changes: [],
    added_intervals: 2,
    removed_intervals: 1,
    previous_occurrences: 4,
    candidate_occurrences: 5,
    previous_unknown_rooms: 0,
    candidate_unknown_rooms: 1,
    warnings: ['stale_source', 'unknown_coverage'],
    by_building_date: [{ building: 'SYN-A', date: '2026-11-01', bookings: 5 }],
  },
  candidate_id: null,
}
async function setup(page: import('@playwright/test').Page) {
  let stages = 0,
    publishes = 0
  let loggedIn = false
  await page.route('**/ops/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/ops/login') {
      loggedIn = true
      await route.fulfill({ json: { authenticated: true } })
      return
    }
    if (!loggedIn) {
      await route.fulfill({ status: 401, json: { error: { code: 'authentication_required' } } })
      return
    }
    if (path === '/ops/session') {
      await route.fulfill({ json: { csrf: 'synthetic-csrf' } })
      return
    }
    if (route.request().method() !== 'GET')
      expect(route.request().headers()['x-csrf-token']).toBe('synthetic-csrf')
    if (path.endsWith('/stage')) stages++
    if (path.endsWith('/publish')) publishes++
    await route.fulfill({
      json:
        path === '/ops/health'
          ? health
          : path === '/ops/batches'
            ? { batch_id: 'synthetic-batch' }
            : path.endsWith('/preview')
              ? preview
              : path.endsWith('/stage')
                ? { dataset_id: dataset }
                : path.endsWith('/publish')
                  ? { health, publication: { status: 'published' } }
                  : { ok: true },
    })
  })
  await page.goto('/operator.html')
  await page.getByLabel('Operator secret').fill('synthetic-secret-not-a-real-credential')
  await page.getByRole('button', { name: 'Unlock private dashboard' }).click()
  await expect(page.getByRole('heading', { name: 'Data health & publication' })).toBeVisible()
  return { stages: () => stages, publishes: () => publishes }
}
async function fillImport(page: import('@playwright/test').Page, format = 'weekly') {
  await page.getByRole('button', { name: 'Import timetable', exact: true }).click()
  await choose(page, 'Source format', format === 'weekly' ? 'Weekly exports' : 'Daily exports')
  await setDate(page, 'Target start date', '2026-11-01')
  await page.getByLabel('Inventory and expected windows').fill(
    JSON.stringify({
      window: { start: '08:00', end: '10:00' },
      buildings: [
        {
          source_name: 'Synthetic A',
          code: 'SYN-A',
          name: 'Synthetic A',
          rooms: [{ source_name: 'SYN-A-101', room_number: '101', source_id: 1, capacity: 20 }],
        },
      ],
    }),
  )
  await page.getByLabel('Structured review reason').fill('synthetic-review')
  await page.getByRole('checkbox', { name: /I reviewed/ }).check()
  for (const date of format === 'weekly' ? [days[0]] : days) {
    await page.getByLabel(`Export for ${date}`, { exact: true }).setInputFiles({
      name: 'sanitized-synthetic.html',
      mimeType: 'text/html',
      buffer: Buffer.from('<html><body>Synthetic test fixture</body></html>'),
    })
    await page
      .getByLabel(`Actual capture timestamp for ${date}`, { exact: true })
      .fill('2026-10-25T11:00:00Z')
  }
}
for (const theme of ['light', 'dark'])
  test(`private overview, wizard and explicit publication in ${theme}`, async ({ page }, info) => {
    const calls = await setup(page)
    await choose(page, 'Appearance', theme)
    await expect(page.getByText('Stale source: importing again')).toBeVisible()
    await page.screenshot({
      path: info.outputPath(`operator-overview-${theme}.png`),
      fullPage: true,
      animations: 'disabled',
    })
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
    await fillImport(page)
    await page.screenshot({
      path: info.outputPath(`operator-wizard-${theme}.png`),
      fullPage: true,
      animations: 'disabled',
    })
    await page
      .getByRole('button', { name: 'Validate & compare (no database writes)', exact: true })
      .click()
    await expect(page.getByRole('heading', { name: '4. Validation & comparison' })).toBeVisible()
    expect(calls.stages()).toBe(0)
    expect(calls.publishes()).toBe(0)
    await page.screenshot({
      path: info.outputPath(`operator-comparison-${theme}.png`),
      fullPage: true,
      animations: 'disabled',
    })
    await expect(
      page.getByRole('button', { name: 'Stage reviewed candidate', exact: true }),
    ).toBeDisabled()
    await page
      .getByRole('checkbox', { name: 'I reviewed the candidate comparison and warnings.' })
      .check()
    await page.getByRole('button', { name: 'Stage reviewed candidate', exact: true }).click()
    await expect(page.getByText('Staged candidate:', { exact: false })).toBeVisible()
    expect(calls.publishes()).toBe(0)
    await page.getByRole('button', { name: 'Review publication', exact: true }).click()
    await expect(page.getByRole('dialog', { name: 'Confirm dataset publication' })).toBeVisible()
    await page.screenshot({
      path: info.outputPath(`operator-confirmation-${theme}.png`),
      animations: 'disabled',
    })
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    expect(calls.publishes()).toBe(0)
    await page.getByRole('button', { name: 'Review publication', exact: true }).click()
    await page
      .getByRole('checkbox', {
        name: 'I reviewed this publication identifier, baseline, and warnings.',
      })
      .check()
    await page.getByRole('button', { name: 'Confirm publish dataset', exact: true }).click()
    await expect(page.getByText(`Publication verified: ${dataset}`)).toBeVisible()
    expect(calls.publishes()).toBe(1)
  })
test('daily import, missing files, and recoverable preview failure', async ({ page }) => {
  const calls = await setup(page)
  await fillImport(page, 'daily')
  await page.getByLabel(`Export for ${days[6]}`, { exact: true }).setInputFiles([])
  // Clearing the input does not discard the chosen File; changing format starts a fresh source selection.
  await choose(page, 'Source format', 'Weekly exports')
  await page
    .getByRole('button', { name: 'Validate & compare (no database writes)', exact: true })
    .click()
  await expect(page.getByRole('alert')).toContainText('Missing export')
  await fillImport(page, 'daily')
  await page.route('**/ops/batches/*/preview', (route) =>
    route.fulfill({ status: 409, json: { error: { code: 'missing_or_unexpected_rooms' } } }),
  )
  await page
    .getByRole('button', { name: 'Validate & compare (no database writes)', exact: true })
    .click()
  await expect(page.getByRole('alert')).toContainText('missing or unexpected rooms')
  expect(calls.stages()).toBe(0)
  expect(calls.publishes()).toBe(0)
  await page.unroute('**/ops/batches/*/preview')
  await page
    .getByRole('button', { name: 'Validate & compare (no database writes)', exact: true })
    .click()
  await expect(page.getByRole('heading', { name: '4. Validation & comparison' })).toBeVisible()
})

test('expired authorization returns to login without retaining private dashboard state', async ({
  page,
}) => {
  await setup(page)
  await expect(page.getByRole('heading', { name: 'Recent import findings' })).toBeVisible()
  await page.route('**/ops/health', (route) =>
    route.fulfill({ status: 401, json: { error: { code: 'authentication_required' } } }),
  )
  await page.getByRole('button', { name: 'Refresh health', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Unlock private dashboard', exact: true }),
  ).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Data health & publication' })).toHaveCount(0)
})
