import assert from 'node:assert/strict'
import test from 'node:test'
import { roomLabel } from '../../src/rooms.ts'
import { themeChoice } from '../../src/preferences.ts'

test('full identifiers use building code and room number without guessing', () => {
  for (const [building_code, room_number, expected] of [
    ['AA', '112', 'AA-112'],
    ['IA', '1120', 'IA-1120'],
    ['HL', 'B101', 'HL-B101'],
  ])
    assert.equal(roomLabel({ building_code, room_number }), expected)
})

test('theme defaults to system and accepts only known locally stored choices', () => {
  for (const invalid of [null, undefined, '', 'Dark', 'automatic', '<script>']) {
    assert.equal(themeChoice(invalid), 'system')
  }
  for (const choice of ['light', 'dark', 'system']) assert.equal(themeChoice(choice), choice)
})
