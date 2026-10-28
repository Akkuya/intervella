import assert from 'node:assert/strict'
import test from 'node:test'
import { readLocation, searchParams, requestParams } from '../../src/search.ts'

const now = new Date('2026-10-14T12:00:00Z')

test('default search is current time, not a hardcoded demo date', () => {
  const { search, error } = readLocation('', now)
  assert.equal(error, undefined)
  assert.equal(search.mode, 'now')
  assert.equal(requestParams(search, now).start, now.toISOString())
})

test('custom date, time, offset and filters round-trip through URL', () => {
  const first = readLocation(
    '?mode=custom&date=2026-11-01&time=01%3A30&offset=-05%3A00&duration=90&building=A',
    now,
  )
  assert.equal(first.error, undefined)
  assert.deepEqual(readLocation(`?${searchParams(first.search)}`, now).search, first.search)
  assert.equal(requestParams(first.search, now).start, '2026-11-01T06:30:00.000Z')
})

test('unsafe or malformed bookmark values produce actionable errors', () => {
  for (const query of [
    '?mode=other',
    '?duration=0',
    '?duration=241',
    '?duration=NaN',
    '?room=../1',
    '?schedule_date=bad',
  ]) {
    assert.ok(readLocation(query, now).error)
  }
})

test('now bookmarks keep dynamic semantics and custom searches require date/time', () => {
  assert.ok(readLocation('?mode=custom', now).error)
  const first = readLocation('?mode=now&duration=30', now)
  assert.equal(
    requestParams(first.search, new Date('2026-10-14T13:00:00Z')).start,
    '2026-10-14T13:00:00.000Z',
  )
})
