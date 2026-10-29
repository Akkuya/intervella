import assert from 'node:assert/strict'
import test from 'node:test'
import { readLocation, searchParams, requestParams } from '../../src/search.ts'

test('an expired search does not invalidate independent room and building calendars', () => {
  const query = '?mode=now&end_date=2026-10-14&end_time=09%3A00&schedule_date=2026-10-15'
  const later = new Date('2026-10-14T12:56:00Z')
  assert.equal(readLocation(query, new Date('2026-10-14T12:50:00Z')).error, undefined)
  assert.ok(readLocation(query, later).error)
  assert.equal(readLocation(query + '&view=buildings&building=SYN-A', later).error, undefined)
  assert.equal(readLocation(query + '&room=1', later).error, undefined)
  assert.ok(readLocation('?view=buildings&schedule_date=bad', later).error)
})

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

test('now bookmarks ignore legacy fixed date and offset fields', () => {
  const location = readLocation('?mode=now&date=2020-01-01&time=01%3A00&offset=-05%3A00', now)
  assert.equal(location.search.date, '2026-10-14')
  assert.equal(location.search.time, '08:00')
  assert.equal(location.search.offset, '')
})

test('until searches restore both Toronto instants and smart filters', () => {
  const query =
    '?mode=custom&date=2026-11-01&time=01%3A30&offset=-04%3A00&end_date=2026-11-01&end_time=01%3A30&end_offset=-05%3A00&room_name=AA112&sort=duration&include_next=1'
  const first = readLocation(query, now)
  assert.equal(first.error, undefined)
  assert.equal(requestParams(first.search, now).end, '2026-11-01T06:30:00.000Z')
  assert.equal(requestParams(first.search, now).duration_minutes, undefined)
  assert.deepEqual(readLocation(`?${searchParams(first.search)}`, now).search, first.search)
  for (const bad of ['&sort=unsafe', '&end_offset=bad', '&end_date=bad']) {
    const changed = new URLSearchParams(query)
    const [key, value] = bad.slice(1).split('=')
    changed.set(key, value)
    assert.ok(readLocation(`?${changed}`, now).error)
  }
})
