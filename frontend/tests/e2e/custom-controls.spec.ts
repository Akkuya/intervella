import { visit } from './control-helpers.ts'
import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mockAPI } from './fixtures.ts'
import { choose, setDate, setTime, selectTrigger, finishClosing } from './control-helpers.ts'
test.beforeEach(async ({ page }) => {
  await mockAPI(page)
})
for (const theme of ['light', 'dark'])
  test(`opened custom controls in ${theme}`, async ({ page }, info) => {
    await visit(page, '/')
    await choose(page, 'Appearance', theme)
    await selectTrigger(page, 'Building').click()
    await page.screenshot({ animations: 'disabled', path: info.outputPath(`select-${theme}.png`) })
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
    await page.keyboard.press('Escape')
    await finishClosing(page)
    await page.getByLabel('Choose a time').check()
    await page.getByRole('button', { name: /^Date: / }).click()
    await expect(page.getByRole('grid')).toBeVisible()
    await page.screenshot({ animations: 'disabled', path: info.outputPath(`date-${theme}.png`) })
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
    await page.keyboard.press('Escape')
    await finishClosing(page)
    await expect(page.getByRole('button', { name: /^Date: / })).toBeFocused()
    await page.getByRole('button', { name: /^Start time: / }).click()
    const minutes = page.getByRole('radiogroup', { name: 'Minute', exact: true }).getByRole('radio')
    await expect(minutes).toHaveCount(12)
    expect(
      await minutes.evaluateAll((els) => els.map((el) => el.closest('label')!.textContent!.trim())),
    ).toEqual(['00', '05', '10', '15', '20', '25', '30', '35', '40', '45', '50', '55'])
    await page.screenshot({ animations: 'disabled', path: info.outputPath(`time-${theme}.png`) })
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
    await page.getByLabel('Type a time').fill('1431')
    await page.getByRole('button', { name: 'Use time', exact: true }).click()
    await expect(page.getByRole('alert').filter({ hasText: 'five-minute' })).toBeVisible()
    await page.getByLabel('Type a time').fill('1430')
    await page.getByRole('button', { name: 'Use time', exact: true }).click()
    await expect(page.getByRole('button', { name: /^Start time: / })).toContainText('2:30 PM')
  })
test('calendar selection updates URL and end shortcuts cross midnight', async ({ page }) => {
  await visit(page, '/?mode=custom&date=2026-10-14&time=23%3A30')
  await setDate(page, 'Date', '2026-10-15')
  await setTime(page, 'Start time', '11:30 PM')
  await choose(page, 'Search length', 'until')
  await page.getByRole('button', { name: /^Available until: / }).click()
  await page.getByLabel('Type a time').fill('00:31')
  await page.getByRole('button', { name: 'Use time', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'five-minute' })).toBeVisible()
  await page.getByRole('button', { name: /^\+1 hr .*12:30 AM$/ }).click()
  await expect(page).toHaveURL(/end_date=2026-10-16/)
  await expect(page).toHaveURL(/end_time=00%3A30/)
  await expect(page.locator('.search-filters summary')).toContainText(
    'Until 12:30 AM on 2026-10-16',
  )
  await visit(page, '/?view=buildings&building=SYN-A&schedule_date=2026-10-14')
  await page.getByRole('button', { name: /^Schedule date: / }).click()
  const day = page.getByRole('button', { name: /Thursday, October 15, 2026/ })
  await day.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/schedule_date=2026-10-15/)
})
test('saved off-grid times stay unchanged and Free now retains exact seconds', async ({ page }) => {
  await visit(page, '/?mode=custom&date=2026-10-14&time=08%3A02')
  await page.getByRole('button', { name: /^Start time: / }).click()
  await expect(page.getByLabel('Type a time')).toHaveValue('8:02 AM')
  await page.keyboard.press('Escape')
  await finishClosing(page)
  await expect(page).toHaveURL(/time=08%3A02/)
  await page.clock.setFixedTime(new Date('2026-10-14T12:02:37.123Z'))
  const request = page.waitForRequest(
    (r) =>
      r.url().includes('/room-search') &&
      new URL(r.url()).searchParams.get('start') === '2026-10-14T12:02:37.123Z',
  )
  await page.getByLabel('Free now', { exact: true }).check()
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await request
  await page.getByLabel('Choose a time').check()
  await expect(page.getByRole('button', { name: /^Start time: / })).toContainText('8:05 AM')
  await page.getByLabel('Free now', { exact: true }).check()
  await page.clock.setFixedTime(new Date('2026-10-15T03:59:59Z'))
  await page.getByLabel('Choose a time').check()
  await expect(page.getByRole('button', { name: /^Start time: / })).toContainText('12:00 AM')
  await expect(page.getByRole('button', { name: /^Date: / }).locator('time')).toHaveAttribute(
    'datetime',
    '2026-10-15',
  )
})

test('split controls support keyboard and disable the Toronto spring gap', async ({ page }) => {
  await visit(page, '/?mode=custom&date=2026-03-08&time=01%3A30')
  await page.getByRole('button', { name: /^Start time: / }).click()
  await selectTrigger(page, 'Hour').click()
  const hours = page.getByRole('listbox', { name: 'Hour' }).getByRole('option')
  await expect(hours).toHaveCount(12)
  await expect(hours.filter({ hasText: /^2$/ })).toHaveAttribute('aria-disabled', 'true')
  await page.clock.pauseAt(new Date('2026-10-14T12:00:05Z'))
  await page.keyboard.press('Escape')
  await finishClosing(page)
  // Nested focus restoration runs on the next animation frame, including with a paused clock.
  await page.clock.runFor(32)
  await expect(selectTrigger(page, 'Hour')).toBeFocused()
  await page
    .getByRole('radiogroup', { name: 'Minute', exact: true })
    .getByRole('radio', { name: '30', exact: true })
    .focus()
  await page.keyboard.press('ArrowRight')
  await expect(page.getByRole('radio', { name: '35', exact: true })).toBeChecked()
  await page.getByRole('radiogroup', { name: 'AM or PM' }).getByText('PM', { exact: true }).click()
  await page.getByRole('button', { name: 'Use time', exact: true }).click()
  await finishClosing(page)
  await expect(page.getByRole('button', { name: /^Start time: / })).toContainText('1:35 PM')
})
test('calendar today is Toronto-based and an open popup follows system theme', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-10-15T04:30:00Z'))
  await page.emulateMedia({ colorScheme: 'light' })
  await visit(page, '/?mode=custom&date=2026-10-14&time=08%3A00')
  await page.getByRole('button', { name: /^Date: / }).click()
  await expect(page.locator('.calendar-day[data-today]')).toHaveText('15')
  const popup = page.locator('.picker-popover')
  const light = await popup.evaluate((el) => getComputedStyle(el).backgroundColor)
  await page.emulateMedia({ colorScheme: 'dark' })
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  expect(await popup.evaluate((el) => getComputedStyle(el).backgroundColor)).not.toBe(light)
  await page.getByRole('button', { name: 'Next month', exact: true }).click()
  await expect(page.getByRole('grid')).toHaveAttribute('aria-label', /November 2026/)
  await page.getByRole('button', { name: 'Previous month', exact: true }).click()
  await page.getByRole('button', { name: /Thursday, October 15, 2026/ }).focus()
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('Enter')
  await finishClosing(page)
  await expect(page.getByRole('button', { name: /^Date: / }).locator('time')).toHaveAttribute(
    'datetime',
    '2026-10-16',
  )
})

test('long selector scrolls to its selected option and supports typeahead', async ({ page }) => {
  await visit(page, '/?duration=240')
  await selectTrigger(page, 'Duration').click()
  const list = page.getByRole('listbox', { name: 'Duration', exact: true })
  const selected = list.getByRole('option', { name: '240 minutes', exact: true })
  await expect(selected).toHaveAttribute('aria-selected', 'true')
  await expect(selected).toBeInViewport()
  await page.keyboard.type('90')
  await page.keyboard.press('Enter')
  await finishClosing(page)
  await expect(selectTrigger(page, 'Duration')).toContainText('90 minutes')
})

test('elapsed end shortcuts name the repeated DST occurrence', async ({ page }) => {
  await visit(page, '/?mode=custom&date=2026-11-01&time=01%3A30&offset=-04%3A00')
  await choose(page, 'Search length', 'until')
  await page.getByRole('button', { name: /^Available until: / }).click()
  await page.getByRole('button', { name: '+1 hr · 1:30 AM EST', exact: true }).click()
  await finishClosing(page)
  await expect(selectTrigger(page, 'End time occurrence')).toContainText('Second occurrence (EST)')
  const request = page.waitForRequest(
    (r) =>
      r.url().includes('/room-search') &&
      new URL(r.url()).searchParams.get('end') === '2026-11-01T06:30:00.000Z',
  )
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await request
})

test('a new end picker initializes to the nearest permitted five-minute time', async ({ page }) => {
  await visit(page, '/?mode=custom&date=2026-10-14&time=08%3A00')
  await choose(page, 'Search length', 'until')
  await page.getByRole('button', { name: /^Available until: / }).click()
  await expect(page.getByLabel('Type a time')).toHaveValue('8:05 AM')
  await page.getByRole('button', { name: 'Use time', exact: true }).click()
  await finishClosing(page)
  await expect(page.getByRole('button', { name: /^Available until: / })).toContainText('8:05 AM')
})
