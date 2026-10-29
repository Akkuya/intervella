import assert from 'node:assert/strict'
import test from 'node:test'
import {
  campusDate,
  campusTime,
  campusTimeLabel,
  dateLabel,
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
  assert.equal(nextBookingLabel('2026-11-01T05:30:00Z', '2026-11-01T04:00:00Z'), '1:30 AM EDT')
  assert.equal(nextBookingLabel('2026-11-01T06:30:00Z', '2026-11-01T04:00:00Z'), '1:30 AM EST')
})

test('overnight endpoint labels include their campus date and offset', () => {
  assert.match(nextBookingLabel('2026-10-15T04:30:00Z', '2026-10-15T03:30:00Z'), /Oct 15.*12:30 AM/)
})

test('friendly Toronto labels handle noon, midnight, summer and winter', () => {
  assert.equal(campusTimeLabel('2026-07-01T16:00:00Z'), '12:00 PM')
  assert.equal(campusTimeLabel('2026-12-01T17:00:00Z'), '12:00 PM')
  assert.equal(campusTimeLabel('2026-10-15T04:00:00Z'), '12:00 AM')
  assert.equal(dateLabel('2026-10-15T02:30:00Z'), 'Wed, Oct 14')
  assert.match(nextBookingLabel('2027-01-01T05:30:00Z', '2027-01-01T04:30:00Z'), /2027.*12:30 AM/)
})
