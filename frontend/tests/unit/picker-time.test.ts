import test from 'node:test'
import assert from 'node:assert/strict'
import { parseTimeText, nearestFive, allowedTime, endSuggestions } from '../../src/picker-time.ts'

test('time entry accepts friendly/24-hour formats without silently rounding', () => {
  for (const input of ['2:30 PM', '14:30', '1430']) assert.equal(parseTimeText(input), '14:30')
  assert.equal(parseTimeText('12:00 AM'), '00:00')
  for (const input of ['14:31', '24:00', '13 PM', '12:60', 'garbage'])
    assert.throws(() => parseTimeText(input))
  assert.equal(nearestFive('23:58'), '00:00')
})
test('picker constraints and shortcuts use real Toronto instants through midnight/DST', () => {
  assert.equal(allowedTime('2026-03-08', '02:30'), false)
  assert.equal(allowedTime('2026-11-01', '01:30'), true)
  assert.equal(allowedTime('2026-10-14', '09:00', '2026-10-14T13:00:00Z'), false)
  const overnight = endSuggestions('2026-10-15T03:30:00Z')[0]
  assert.equal(overnight.date, '2026-10-15')
  assert.equal(overnight.time, '00:00')
  const fold = endSuggestions('2026-11-01T05:30:00Z')[1]
  assert.equal(fold.time, '01:30')
  assert.equal(fold.offset, '-05:00')
})
