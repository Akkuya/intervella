import assert from 'node:assert/strict'
import test from 'node:test'
import { parseFavourites, toggleFavourite } from '../../src/favourites.ts'

test('local favourites accept only bounded unique identifiers, never cached schedule data', () => {
  assert.deepEqual(parseFavourites('bad'), { rooms: [], buildings: [] })
  assert.deepEqual(
    parseFavourites(
      JSON.stringify({
        rooms: [1, 1, -2, '3', 999],
        buildings: ['AA', 'AA', '<script>', 'IA'],
        availability: 'private',
      }),
    ),
    { rooms: [1, 999], buildings: ['AA', 'IA'] },
  )
  const first = toggleFavourite({ rooms: [], buildings: [] }, 'rooms', 1)
  assert.deepEqual(first.rooms, [1])
  assert.deepEqual(toggleFavourite(first, 'rooms', 1).rooms, [])
  assert.equal(
    parseFavourites(JSON.stringify({ rooms: Array.from({ length: 150 }, (_, i) => i + 1) })).rooms
      .length,
    100,
  )
})
