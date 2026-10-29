import assert from 'node:assert/strict'
import test from 'node:test'
import { layoutEvents, positionRange, shiftDay, eventLabel } from '../../src/calendar-layout.ts'
import { schedule } from '../e2e/fixtures.ts'

const window = {
  start: '2026-11-01T04:00:00Z',
  end: '2026-11-02T05:00:00Z',
  timezone: 'America/Toronto' as const,
}
test('calendar geometry uses UTC duration across a 25-hour day and clips midnight crossings', () => {
  assert.deepEqual(positionRange('2026-11-01T03:30:00Z', '2026-11-01T05:00:00Z', window), {
    left: 0,
    width: 4,
  })
  assert.equal(positionRange('2026-10-31T04:00:00Z', '2026-10-31T05:00:00Z', window), null)
  assert.equal(shiftDay('2026-11-01', 1), '2026-11-02')
  assert.equal(shiftDay('2027-01-01', -1), '2026-12-31')
})
test('overlapping event labels get separate lanes while adjacent events can share one', () => {
  const meetings = [
    {
      ...schedule.data[0],
      id: 1,
      starts_at: '2026-11-01T05:00:00Z',
      ends_at: '2026-11-01T06:00:00Z',
    },
    {
      ...schedule.data[0],
      id: 2,
      starts_at: '2026-11-01T05:30:00Z',
      ends_at: '2026-11-01T06:30:00Z',
    },
    {
      ...schedule.data[0],
      id: 3,
      starts_at: '2026-11-01T06:00:00Z',
      ends_at: '2026-11-01T07:00:00Z',
    },
  ]
  assert.deepEqual(
    layoutEvents(meetings, window).map((item) => item.lane),
    [0, 1, 0],
  )
  assert.equal(eventLabel(schedule.data[0]), 'Scheduled event')
})
