export type Theme = 'light' | 'dark' | 'system'
export const THEME_KEY = 'utscvacant.appearance'
export const themeChoice = (value: unknown): Theme =>
  value === 'light' || value === 'dark' ? value : 'system'
