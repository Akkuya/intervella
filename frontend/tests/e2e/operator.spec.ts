import type { InventoryBuilding, InventoryProfile, SourceAnalysis } from '../../src/operator-api.ts'
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
const generatedBuildings: InventoryBuilding[] = [
  {
    source_name: 'Synthetic A',
    code: 'SYN-A',
    name: 'Synthetic A',
    rooms: [
      {
        source_name: 'SYN-A-101',
        room_number: '101',
        source_id: 9001,
        capacity: 20,
        window: { start: '08:00', end: '10:00' },
      },
    ],
  },
]
function generated(format: 'daily' | 'weekly' = 'weekly'): SourceAnalysis {
  const files = (format === 'weekly' ? [days[0]] : days).map((day, index) => ({
    file: `synthetic-${index}.html`,
    period: day,
    format,
    bytes: 100,
    sha256: 'a'.repeat(64),
    rooms: 1,
    dates: [day],
    row_steps: [30],
  }))
  return {
    analysis_hash: 'a'.repeat(64),
    source_format: format,
    start_date: days[0],
    profile_version: 1,
    bootstrap_required: false,
    missing_sources: [],
    files,
    observed_rooms: [],
    issues: [],
    differences: {
      added_rooms: [],
      missing_rooms: [],
      capacity_changes: [],
      window_changes: [],
      source_id_changes: [],
      unmatched_rooms: [],
    },
    summary: { rooms: 1, buildings: 1, occurrences: 5, dates: days },
    draft: {
      version: format === 'weekly' ? 2 : 1,
      source_format: format,
      start_date: days[0],
      window: { start: '08:00', end: '10:00' },
      buildings: generatedBuildings,
      ...(format === 'weekly'
        ? {
            inventory_scope: 'complete',
            inventory_review_reason: '',
            weeks: files.map((f) => ({ week_start: f.period, file: f.file, fetched_at: '' })),
          }
        : { snapshots: files.map((f) => ({ date: f.period, file: f.file, fetched_at: '' })) }),
    },
  }
}

async function setup(page: import('@playwright/test').Page, bootstrap = false) {
  let stages = 0,
    publishes = 0
  let loggedIn = false
  let approvedProfile: InventoryProfile | null = bootstrap
    ? null
    : {
        version: 1,
        reviewed_at: '2026-10-25T11:00:00Z',
        review_reason: 'synthetic-review',
        expected_rooms: 1,
        expected_buildings: 1,
        source_formats: ['weekly', 'daily'],
        window: { start: '08:00', end: '10:00' },
        buildings: generatedBuildings,
      }
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
    if (path === '/ops/inventory-profile') {
      if (route.request().method() === 'PUT') {
        const payload = route.request().postDataJSON()
        expect(payload.review_acknowledged).toBe(true)
        expect(payload.expected_rooms).toBe(
          payload.buildings.reduce((n: number, b: { rooms: unknown[] }) => n + b.rooms.length, 0),
        )
        approvedProfile = {
          ...payload,
          version: (approvedProfile?.version ?? 0) + 1,
          reviewed_at: '2026-10-25T11:00:00Z',
        }
      }
      await route.fulfill({ json: { profile: approvedProfile, history: [] } })
      return
    }
    if (path.endsWith('/analyze')) {
      const format = (
        await page.getByRole('button', { name: /Source format$/ }).textContent()
      )?.includes('Daily')
        ? 'daily'
        : 'weekly'
      const result = generated(format)
      result.bootstrap_required = !approvedProfile
      result.profile_version = approvedProfile?.version ?? 0
      if (approvedProfile) {
        result.draft.buildings = approvedProfile.buildings
        result.draft.window = approvedProfile.window
      } else
        result.draft.buildings = generatedBuildings.map((b) => ({
          ...b,
          rooms: b.rooms.map((r) => ({
            ...r,
            source_id: format === 'weekly' ? null : r.source_id,
          })),
        }))
      await route.fulfill({ json: result })
      return
    }
    if (path.endsWith('/manifest')) {
      await route.fulfill({
        json: {
          manifest: route.request().postDataJSON().manifest,
          profile_version: 1,
          summary: {},
        },
      })
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
  await expect(page).toHaveTitle('Intervella · Private operations')
  await expect(page.locator('body')).not.toContainText(/UTSCVacant|RoomFinder/)
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute('href', '/assets/intervella.svg')
  const icon = await page.request.get('/assets/intervella.svg')
  expect(icon.ok()).toBe(true)
  await expect(page.getByRole('button', { name: 'Unlock private dashboard' })).toBeVisible()
  await page.screenshot({
    path: test.info().outputPath('operator-login.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await page.getByLabel('Operator secret').fill('synthetic-secret-not-a-real-credential')
  await page.getByRole('button', { name: 'Unlock private dashboard' }).click()
  await expect(page.getByRole('heading', { name: 'Data health & publication' })).toBeVisible()
  return {
    stages: () => stages,
    publishes: () => publishes,
    advanceProfile: () => {
      if (approvedProfile)
        approvedProfile = { ...approvedProfile, version: approvedProfile.version + 1 }
    },
  }
}
async function fillImport(page: import('@playwright/test').Page, format = 'weekly') {
  await page.getByRole('button', { name: 'Import timetable', exact: true }).click()
  await setDate(page, 'Target start date', days[0])
  await choose(page, 'Source format', format === 'weekly' ? 'Weekly exports' : 'Daily exports')
  await page.getByLabel('Authorized HTML exports', { exact: true }).setInputFiles(
    (format === 'weekly' ? [days[0]] : days).map((_, i) => ({
      name: `synthetic-${i}.html`,
      mimeType: 'text/html',
      buffer: Buffer.from('<html><body>Synthetic fixture</body></html>'),
    })),
  )
  await page.getByRole('button', { name: 'Analyze & generate draft', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: '3. Review generated manifest', exact: true }),
  ).toBeVisible()
  for (const [index] of (format === 'weekly' ? [days[0]] : days).entries())
    await page
      .getByLabel(`Actual capture timestamp for synthetic-${index}.html`, { exact: true })
      .fill('2026-10-25T11:00:00Z')
  await page.getByLabel('Review reason (short code)', { exact: true }).fill('synthetic-review')
  await page
    .getByRole('checkbox', { name: 'I reviewed the target dates, year and source-file mappings.' })
    .check()
  await page
    .getByRole('checkbox', {
      name: 'I confirm these are the actual capture timestamps for the original exports.',
    })
    .check()
}
for (const theme of ['light', 'dark'] as const)
  for (const width of [360, 390, 430, 768, 1024, 1440])
    test(`private overview, wizard and explicit publication at ${width}px in ${theme}`, async ({
      page,
    }, info) => {
      await page.setViewportSize({ width, height: 900 })
      await page.emulateMedia({ colorScheme: theme })
      const calls = await setup(page)
      await choose(page, 'Appearance', theme)
      await expect(page.getByText('Stale source: importing again')).toBeVisible()
      await page.screenshot({
        path: info.outputPath(`operator-overview-${theme}.png`),
        fullPage: true,
        animations: 'disabled',
      })
      expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      await fillImport(page)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
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
      await page.getByRole('button', { name: 'Import history', exact: true }).click()
      await expect(page.getByRole('heading', { name: 'Audited import history' })).toBeVisible()
      await page.getByRole('button', { name: /succeeded.*published/ }).click()
      await expect(page.getByText('synthetic-review', { exact: true })).toBeVisible()
      await page.screenshot({
        path: info.outputPath(`operator-history-${theme}.png`),
        fullPage: true,
        animations: 'disabled',
      })
    })
test('daily import and recoverable preview failure retain editable review', async ({ page }) => {
  const calls = await setup(page)
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

test('first import requires independent profile approval and supports structured correction', async ({
  page,
}, info) => {
  const calls = await setup(page, true)
  await fillImport(page)
  await expect(
    page.getByRole('button', { name: 'Validate & compare (no database writes)', exact: true }),
  ).toBeDisabled()
  await expect(page.getByLabel('Independently expected rooms', { exact: true })).toHaveValue('')
  await page.locator('.ops-mapping-group > summary').click()
  await page.getByLabel('Canonical building code', { exact: true }).fill('REVIEWED')
  await page.getByLabel('Independently expected rooms', { exact: true }).fill('1')
  await page.getByLabel('Independently expected buildings', { exact: true }).fill('1')
  await expect(
    page.getByRole('button', { name: 'Approve inventory profile', exact: true }),
  ).toBeDisabled()
  await page
    .getByRole('checkbox', {
      name: 'I independently verified the expected inventory and coverage; parsed rows alone are not proof.',
    })
    .check()
  await page.screenshot({
    path: info.outputPath('bootstrap-inventory-review.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await page.getByRole('button', { name: 'Approve inventory profile', exact: true }).click()
  await expect(page.getByText(/Approved inventory profile v1 saved privately/)).toBeVisible()
  await expect(page.locator('.ops-generated-review')).toContainText(
    'Mappings match approved profile v1',
  )
  await page
    .getByRole('button', { name: 'Validate & compare (no database writes)', exact: true })
    .click()
  await expect(page.getByRole('heading', { name: '4. Validation & comparison' })).toBeVisible()
  expect(calls.stages()).toBe(0)
  expect(calls.publishes()).toBe(0)
  await page.getByText('Advanced: inspect, edit or download manifest JSON', { exact: true }).click()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download manifest JSON', exact: true }).click()
  expect((await download).suggestedFilename()).toBe('intervella-manifest-2026-11-01.json')
})

test('source edits invalidate comparison and require fresh capture and target confirmation', async ({
  page,
}) => {
  const calls = await setup(page)
  await fillImport(page)
  await page
    .getByRole('button', { name: 'Validate & compare (no database writes)', exact: true })
    .click()
  await expect(page.getByRole('heading', { name: '4. Validation & comparison' })).toBeVisible()
  await page.getByLabel('Authorized HTML exports', { exact: true }).setInputFiles({
    name: 'synthetic-0.html',
    mimeType: 'text/html',
    buffer: Buffer.from('<html>changed synthetic export</html>'),
  })
  await expect(page.getByRole('heading', { name: '4. Validation & comparison' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '3. Review generated manifest' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Analyze & generate draft', exact: true }).click()
  await expect(
    page.getByRole('checkbox', {
      name: 'I confirm these are the actual capture timestamps for the original exports.',
    }),
  ).not.toBeChecked()
  await expect(
    page.getByRole('checkbox', {
      name: 'I reviewed the target dates, year and source-file mappings.',
    }),
  ).not.toBeChecked()
  expect(calls.stages()).toBe(0)
  expect(calls.publishes()).toBe(0)
})

test('coverage editor uses half-hour choices while leaving invalid typed minutes uncommitted', async ({
  page,
}, info) => {
  await setup(page)
  await fillImport(page)
  const trigger = page.getByRole('button', { name: /^Default expected window start:/ })
  await trigger.focus()
  await page.keyboard.press('Enter')
  const options = page.getByRole('radiogroup', { name: 'Minute', exact: true }).getByRole('radio')
  await expect(options).toHaveCount(2)
  await expect(
    page.getByRole('dialog', { name: 'Default expected window start picker' }),
  ).toBeInViewport()
  await page.screenshot({
    path: info.outputPath('expected-window-picker.png'),
    animations: 'disabled',
  })
  await page.getByLabel('Type a time', { exact: true }).fill('0905')
  await page.getByRole('button', { name: 'Use time', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('half-hour')
  await page.keyboard.press('Escape')
  await expect(trigger).toBeFocused()
})

test('logout clears a staged candidate and permits a new private import after login', async ({
  page,
}) => {
  await setup(page)
  await fillImport(page)
  await page
    .getByRole('button', { name: 'Validate & compare (no database writes)', exact: true })
    .click()
  await page
    .getByRole('checkbox', { name: 'I reviewed the candidate comparison and warnings.' })
    .check()
  await page.getByRole('button', { name: 'Stage reviewed candidate', exact: true }).click()
  await expect(page.getByText('Staged candidate:', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await page.getByLabel('Operator secret').fill('synthetic-secret-not-a-real-credential')
  await page.getByRole('button', { name: 'Unlock private dashboard' }).click()
  await page.getByRole('button', { name: 'Import timetable', exact: true }).click()
  await expect(page.getByLabel('Authorized HTML exports', { exact: true })).toBeEnabled()
  await expect(page.getByText('Staged candidate:', { exact: false })).toHaveCount(0)
})

test('missing adjacent weekly source is informative and never enables validation', async ({
  page,
}) => {
  await setup(page)
  await fillImport(page)
  await page.route('**/ops/batches/*/analyze', (route) => {
    const result = generated()
    result.start_date = result.draft.start_date = '2026-11-04'
    result.summary.dates = Array.from(
      { length: 7 },
      (_, i) => `2026-11-${String(i + 4).padStart(2, '0')}`,
    )
    result.missing_sources = ['2026-11-08']
    return route.fulfill({ json: result })
  })
  await setDate(page, 'Target start date', '2026-11-04')
  await page.getByRole('button', { name: 'Analyze & generate draft', exact: true }).click()
  await expect(
    page.getByRole('status').filter({ hasText: 'Additional weekly exports' }),
  ).toContainText('2026-11-08')
  await expect(
    page.getByRole('button', { name: 'Validate & compare (no database writes)', exact: true }),
  ).toBeDisabled()
})

test('reanalysis recovers from another session approving a newer profile without losing uploads', async ({
  page,
}) => {
  const calls = await setup(page)
  await fillImport(page)
  calls.advanceProfile()
  await page.getByRole('button', { name: 'Analyze & generate draft', exact: true }).click()
  await expect(page.locator('.ops-generated-review')).toContainText(
    'Mappings match approved profile v2',
  )
  await expect(page.locator('.ops-source-list')).toContainText('synthetic-0.html')
  await expect(
    page.getByLabel('Actual capture timestamp for synthetic-0.html', { exact: true }),
  ).toHaveValue('2026-10-25T11:00:00Z')
  await page
    .getByRole('checkbox', {
      name: 'I confirm these are the actual capture timestamps for the original exports.',
    })
    .check()
  await page
    .getByRole('checkbox', { name: 'I reviewed the target dates, year and source-file mappings.' })
    .check()
  const request = page.waitForRequest((r) => r.url().endsWith('/manifest') && r.method() === 'POST')
  await page
    .getByRole('button', { name: 'Validate & compare (no database writes)', exact: true })
    .click()
  expect((await request).postDataJSON().profile_version).toBe(2)
})

test('legacy v1 manifests without source_format retain daily profile compatibility', async ({
  page,
}) => {
  await setup(page, true)
  await page.getByRole('button', { name: 'Import timetable', exact: true }).click()
  await page.getByText('Approved inventory profile — bootstrap required', { exact: true }).click()
  const legacy = generated('daily').draft
  const { source_format, ...value } = legacy
  expect(source_format).toBe('daily')
  await page.getByLabel('Load reviewed profile or manifest', { exact: true }).setInputFiles({
    name: 'synthetic-v1.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify(value)),
  })
  const compatibility = page.getByRole('group', { name: 'Profile compatibility', exact: true })
  await expect(
    compatibility.getByRole('checkbox', { name: 'Daily exports', exact: true }),
  ).toBeChecked()
  await expect(
    compatibility.getByRole('checkbox', { name: 'Weekly exports', exact: true }),
  ).not.toBeChecked()
})
