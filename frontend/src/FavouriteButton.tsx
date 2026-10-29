import { useFavourites } from './favourites.ts'
import { Button } from './ui.tsx'

export function FavouriteButton({
  kind,
  id,
  label,
}: {
  kind: 'rooms' | 'buildings'
  id: number | string
  label: string
}) {
  const { value, toggle } = useFavourites()
  const saved = (value[kind] as (number | string)[]).includes(id)
  const full = value[kind].length >= (kind === 'rooms' ? 100 : 50)
  return (
    <Button
      variant="secondary"
      className="favourite-button"
      aria-label={`${saved ? 'Remove' : 'Save'} ${label}${!saved && full ? ' (limit reached)' : ''}`}
      title={`${saved ? 'Remove' : 'Save'} ${label}${!saved && full ? ' (limit reached)' : ''}`}
      aria-pressed={saved}
      disabled={!saved && full}
      onClick={() => toggle(kind, id)}
    >
      <svg
        aria-hidden="true"
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill={saved ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth="1.8"
      >
        <path d="M6 4h12v17l-6-4-6 4z" strokeLinejoin="round" />
      </svg>
    </Button>
  )
}
