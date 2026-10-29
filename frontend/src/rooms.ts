import type { Room } from './api.ts'

export const roomLabel = (room: Pick<Room, 'building_code' | 'room_number'>) =>
  `${room.building_code}-${room.room_number}`
