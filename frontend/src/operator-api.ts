export interface OpsDay {
  date: string
  fetched_at: string | null
  freshness?: string
  complete_rooms: number
  unknown_rooms: number
  missing_rooms: number
}
export interface OpsRun {
  run_id: string
  status: string
  dataset_id: string | null
  published_at: string | null
  started_at: string
  error_code: string | null
  counts: Record<string, unknown>
}
export interface OpsHealth {
  active: null | {
    dataset_id: string
    published_at: string
    imported_at: string
    source_fetched_at: string
    freshness: string
    source_format: string
    parser_version: string
    rooms: number
    buildings: number | null
    occurrences: number | null
    days: OpsDay[]
  }
  history: OpsRun[]
}
export interface Preview {
  summary: {
    dates: string[]
    rooms: number
    buildings: number
    occurrences: number
    unknown_rooms: number
    source_format: string
    source_fetched_at: string
    input_hash: string
  }
  sources: { date: string; fetched_at: string }[]
  comparison: {
    baseline_dataset_id: string | null
    added_rooms: string[]
    missing_rooms: string[]
    capacity_changes: { room: string; previous: number; candidate: number }[]
    added_intervals: number
    removed_intervals: number
    previous_occurrences: number
    candidate_occurrences: number
    previous_unknown_rooms: number | null
    candidate_unknown_rooms: number
    warnings: string[]
    by_building_date: {
      building: string
      date: string
      bookings: number
      previous?: number
      delta?: number
    }[]
  }
  candidate_id: string | null
}

export async function opsRequest<T>(
  path: string,
  csrf: string,
  method = 'GET',
  body?: unknown,
): Promise<T> {
  const response = await fetch(`/ops/${path}`, {
    method,
    credentials: 'same-origin',
    cache: 'no-store',
    headers: {
      ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
      ...(body !== undefined && !(body instanceof File)
        ? { 'Content-Type': 'application/json' }
        : {}),
    },
    body: body instanceof File ? body : body === undefined ? undefined : JSON.stringify(body),
  })
  const result = await response.json()
  if (!response.ok)
    throw new Error(
      [
        result.error?.code ?? 'operator_request_failed',
        ...(result.error?.report?.anomalies ?? []),
      ].join(': '),
    )
  return result as T
}
