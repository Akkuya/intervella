import { useSyncExternalStore } from 'react'
import type { MouseEvent } from 'react'

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
