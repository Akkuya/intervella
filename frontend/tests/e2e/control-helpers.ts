import { expect } from '@playwright/test'
import type { Page } from '@playwright/test'
export const selectTrigger = (page: Page, label: string) =>
  page.getByRole('button', { name: new RegExp(`${label}$`) })
export function optionText(label: string, value: string) {
  if (label === 'Search length') return value === 'until' ? 'Available until' : 'Duration'
  if (label === 'Sort rooms')
    return (
      {
        building: 'Building, then room',
        room: 'Room number',
        duration: 'Longest known availability',
      } as Record<string, string>
    )[value]
  if (label === 'Appearance') return value[0].toUpperCase() + value.slice(1)
  if (label.includes('occurrence'))
    return value === '-05:00' ? 'Second occurrence (EST)' : 'First occurrence (EDT)'
  if (label === 'Duration') return `${value} minutes`
  return value || 'All buildings'
}
export async function openFilters(page: Page) {
  const url = new URL(page.url())
  if (
    url.pathname.endsWith('operator.html') ||
    url.searchParams.has('room') ||
    (url.searchParams.has('view') && url.searchParams.get('view') !== 'find')
  )
    return
  const filters = page.locator('.search-filters')
  await expect(filters).toBeAttached()
  if ((await filters.getAttribute('open')) === null) await filters.locator('summary').click()
}
export async function choose(page: Page, label: string, value: string) {
  await openFilters(page)
  await selectTrigger(page, label).click()
  const text = optionText(label, value)
  const options = page.getByRole('listbox', { name: label, exact: true }).getByRole('option')
  await options.filter({ hasText: text }).first().click()
  await finishClosing(page)
}
export async function setDate(page: Page, label: string, value: string) {
  await page.getByRole('button', { name: new RegExp(`^${label}: `) }).click()
  await page.getByLabel('Calendar date (YYYY-MM-DD)', { exact: true }).fill(value)
  await page.getByRole('button', { name: 'Use date', exact: true }).click()
  await finishClosing(page)
}
export async function setTime(page: Page, label: string, value: string) {
  await page.getByRole('button', { name: new RegExp(`^${label}: `) }).click()
  await page.getByLabel('Type a time', { exact: true }).fill(value)
  await page.getByRole('button', { name: 'Use time', exact: true }).click()
  await finishClosing(page)
}
export async function selected(page: Page, label: string, value: string) {
  await openFilters(page)
  await expect(selectTrigger(page, label)).toContainText(optionText(label, value))
}

// Finish exit animations without advancing the controlled search clock.
export async function finishClosing(page: Page) {
  await page.locator('.control-popover[data-exiting]').evaluateAll((nodes) => {
    nodes.forEach((node) => node.getAnimations().forEach((animation) => animation.finish()))
  })
}

// Tests that edit filters explicitly expand the otherwise compact search summary.
export async function visit(page: Page, url: string) {
  await page.goto(url)
  await openFilters(page)
}
