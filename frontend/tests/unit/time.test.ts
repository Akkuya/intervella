import assert from 'node:assert/strict'
import test from 'node:test'
import {
  campusDate,
  campusTime,
  localCandidates,
  nextBookingLabel,
  toInstant,
} from '../../src/time.ts'

test('campus date and time are independent of device timezone', () => {
  assert.equal(campusDate('2026-10-15T02:30:00Z'), '2026-10-14')
  assert.equal(campusTime('2026-10-15T02:30:00Z'), '22:30')
})

test('summer and winter wall times convert to UTC', () => {
  assert.equal(toInstant('2026-07-01', '12:00'), '2026-07-01T16:00:00.000Z')
  assert.equal(toInstant('2026-12-01', '12:00'), '2026-12-01T17:00:00.000Z')
})

test('DST gap is rejected and repeated hour needs explicit choice', () => {
  assert.equal(localCandidates('2026-03-08', '02:30').length, 0)
  assert.throws(() => toInstant('2026-03-08', '02:30'), /does not exist/)
  const repeated = localCandidates('2026-11-01', '01:30')
  assert.deepEqual(
    repeated.map((value) => value.offset),
    ['-04:00', '-05:00'],
  )
  assert.throws(() => toInstant('2026-11-01', '01:30'), /occurrence/)
  assert.equal(toInstant('2026-11-01', '01:30', '-05:00'), '2026-11-01T06:30:00.000Z')
  assert.throws(() => toInstant('2026-07-01', '12:00', '-05:00'), /offset/)
})

test('impossible dates and malformed times are rejected', () => {
  for (const [date, time] of [
    ['2026-02-30', '12:00'],
    ['2026-10-14', '24:00'],
    ['bad', '12:00'],
  ]) {
    assert.throws(() => toInstant(date, time))
  }
})

test('displayed bookings distinguish both occurrences of a repeated hour', () => {
  assert.equal(nextBookingLabel('2026-11-01T05:30:00Z', '2026-11-01T04:00:00Z'), '01:30 GMT-04:00')
  assert.equal(nextBookingLabel('2026-11-01T06:30:00Z', '2026-11-01T04:00:00Z'), '01:30 GMT-05:00')
})

test('overnight endpoint labels include their campus date and offset', () => {
  assert.match(
    nextBookingLabel('2026-10-15T04:30:00Z', '2026-10-15T03:30:00Z'),
    /Oct 15, 2026.*00:30 GMT-04:00/,
  )
})
