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
      aria-pressed={saved}
      disabled={!saved && full}
      onClick={() => toggle(kind, id)}
    >
      {saved ? 'Remove' : 'Save'} {label}
      {!saved && full ? ' (limit reached)' : ''}
    </Button>
  )
}
