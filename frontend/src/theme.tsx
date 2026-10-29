import { Select } from './Controls.tsx'
import { useEffect, useState } from 'react'
import { THEME_KEY, themeChoice } from './preferences.ts'
import type { Theme } from './preferences.ts'

export function ThemeControl() {
  const [choice, setChoice] = useState<Theme>(() => {
    try {
      return themeChoice(localStorage.getItem(THEME_KEY))
    } catch {
      return 'system'
    }
  })
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      document.documentElement.dataset.theme =
        choice === 'system' ? (media.matches ? 'dark' : 'light') : choice
      document.documentElement.dataset.appearance = choice
    }
    const storage = (event: StorageEvent) => {
      if (event.key === THEME_KEY || event.key === null) setChoice(themeChoice(event.newValue))
    }
    apply()
    media.addEventListener('change', apply)
    window.addEventListener('storage', storage)
    return () => {
      media.removeEventListener('change', apply)
      window.removeEventListener('storage', storage)
    }
  }, [choice])
  return (
    <label className="appearance-control">
      Appearance
      <Select
        label="Appearance"
        value={choice}
        onChange={(selection) => {
          const next = themeChoice(selection)
          setChoice(next)
          try {
            localStorage.setItem(THEME_KEY, next)
          } catch {
            /* Session preference still works. */
          }
        }}
      >
        <option value="system">System</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </Select>
    </label>
  )
}
