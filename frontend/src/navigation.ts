import { useEffect, useState, useSyncExternalStore } from 'react'
import type { MouseEvent } from 'react'
import { readLocation } from './search.ts'

export function routeClick(event: MouseEvent<HTMLAnchorElement>, params: URLSearchParams) {
  if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
    event.preventDefault()
    navigate(params)
  }
}

function subscribe(callback: () => void) {
  window.addEventListener('popstate', callback)
  return () => window.removeEventListener('popstate', callback)
}

export const useLocationSearch = () => useSyncExternalStore(subscribe, () => window.location.search)

export function useSearchLocation(query: string) {
  const [, tick] = useState(0)
  const location = readLocation(query)
  const end = location.sessionEnd
  const state = location.session?.state
  useEffect(() => {
    if (!end) return
    const refresh = () => tick((value) => value + 1)
    const deadline =
      state === 'expired' ? undefined : Date.parse(end) - (state === 'ending' ? 0 : 5 * 60_000)
    const timer =
      deadline === undefined
        ? undefined
        : window.setTimeout(refresh, Math.max(1, deadline - Date.now() + 1))
    window.addEventListener('visibilitychange', refresh)
    window.addEventListener('focus', refresh)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('visibilitychange', refresh)
      window.removeEventListener('focus', refresh)
    }
  }, [end, state])
  return location
}

export function navigate(params: URLSearchParams, replace = false): boolean {
  const query = params.toString()
  if (window.location.search === (query ? `?${query}` : '')) return false
  window.history[replace ? 'replaceState' : 'pushState'](
    null,
    '',
    `${window.location.pathname}${query ? `?${query}` : ''}`,
  )
  window.dispatchEvent(new PopStateEvent('popstate'))
  return true
}

function subscribeOnline(callback: () => void) {
  window.addEventListener('online', callback)
  window.addEventListener('offline', callback)
  return () => {
    window.removeEventListener('online', callback)
    window.removeEventListener('offline', callback)
  }
}

export const useOnline = () => useSyncExternalStore(subscribeOnline, () => navigator.onLine)
