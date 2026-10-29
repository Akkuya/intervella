import type { ButtonHTMLAttributes, ReactNode } from 'react'
import type { Room } from './api.ts'
import { roomLabel } from './rooms.ts'
import { routeClick } from './navigation.ts'

export function Button({
  variant = 'primary',
  className = '',
  type = 'button',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' }) {
  return <button {...props} type={type} className={`button ${variant} ${className}`} />
}

export function Badge({
  children,
  tone = '',
}: {
  children: ReactNode
  tone?: '' | 'green' | 'amber' | 'neutral'
}) {
  return <span className={`badge ${tone}`}>{children}</span>
}

export function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="state-panel">
      <h3>{title}</h3>
      {children}
    </div>
  )
}

export function RoomCard({
  room,
  params,
  buildingName,
  children,
  status,
}: {
  room: Pick<Room, 'room_id' | 'building_code' | 'room_number' | 'capacity'>
  params: URLSearchParams
  buildingName?: string
  children?: ReactNode
  status: ReactNode
}) {
  const name = roomLabel(room)
  const detail = new URLSearchParams(params)
  detail.set('room', String(room.room_id))
  detail.delete('schedule_date')
  return (
    <article className="room-card" aria-label={name}>
      <div className="room-card-top">
        <span className="building-code">{buildingName ?? room.building_code}</span>
        {status}
      </div>
      <h3>{name}</h3>
      <p className="capacity">
        {room.capacity === null ? 'Capacity not published' : `${room.capacity} seats`}
      </p>
      {children}
      <a
        id={`room-link-${room.room_id}`}
        className="room-link"
        href={`?${detail}`}
        onClick={(event) => routeClick(event, detail)}
      >
        View {name}
        <span aria-hidden="true">↗</span>
      </a>
    </article>
  )
}
