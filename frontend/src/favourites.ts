import { useSyncExternalStore } from 'react'

export interface Favourites {
  rooms: number[]
  buildings: string[]
}
const KEY = 'utscvacant.favourites'
export function parseFavourites(raw: string | null): Favourites {
  try {
    const value: unknown = JSON.parse(raw ?? '{}')
    if (!value || typeof value !== 'object') return { rooms: [], buildings: [] }
    const data = value as Record<string, unknown>
    return {
      rooms: [
        ...new Set(
          Array.isArray(data.rooms)
            ? data.rooms.filter(
                (id): id is number => typeof id === 'number' && Number.isSafeInteger(id) && id > 0,
              )
            : [],
        ),
      ].slice(0, 100),
      buildings: [
        ...new Set(
          Array.isArray(data.buildings)
            ? data.buildings.filter(
                (code): code is string =>
                  typeof code === 'string' && /^[A-Za-z0-9-]{1,32}$/.test(code),
              )
            : [],
        ),
      ].slice(0, 50),
    }
  } catch {
    return { rooms: [], buildings: [] }
  }
}
export function toggleFavourite(
  value: Favourites,
  kind: 'rooms' | 'buildings',
  id: number | string,
): Favourites {
  const selected = value[kind] as (number | string)[]
  return parseFavourites(
    JSON.stringify({
      ...value,
      [kind]: selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id],
    }),
  )
}
let snapshot: Favourites | undefined
const listeners = new Set<() => void>()
function getSnapshot() {
  if (!snapshot) {
    try {
      snapshot = parseFavourites(localStorage.getItem(KEY))
    } catch {
      snapshot = { rooms: [], buildings: [] }
    }
  }
  return snapshot
}
function subscribe(listener: () => void) {
  listeners.add(listener)
  const changed = (event: StorageEvent) => {
    if (event.key === KEY || event.key === null) {
      snapshot = parseFavourites(event.newValue)
      listeners.forEach((notify) => notify())
    }
  }
  window.addEventListener('storage', changed)
  return () => {
    listeners.delete(listener)
    window.removeEventListener('storage', changed)
  }
}
export function useFavourites() {
  const value = useSyncExternalStore(subscribe, getSnapshot)
  return {
    value,
    toggle: (kind: 'rooms' | 'buildings', id: number | string) => {
      snapshot = toggleFavourite(getSnapshot(), kind, id)
      try {
        localStorage.setItem(KEY, JSON.stringify(snapshot))
      } catch {
        /* Session-only when blocked. */
      }
      listeners.forEach((notify) => notify())
    },
  }
}
