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

const errorHelp: Record<string, string> = {
  malformed_or_unexpected_source:
    'An export is malformed or does not match the reviewed target week. Check the target year and choose a complete original HTML export.',
  mixed_source_formats: 'Use daily files or weekly files in one batch, not both.',
  duplicate_source_period: 'Two exports represent the same date or week. Remove the duplicate.',
  missing_source_files: 'Upload the remaining required dates or enclosing Sunday weeks.',
  source_format_mismatch:
    'The selected format does not match the HTML structure. Use detection or select the structurally valid format.',
  profile_changed:
    'Approved inventory changed. Analyze and review against the current profile before continuing.',
  profile_busy: 'Another inventory review or publication is in progress. Retry after it finishes.',
  profile_review_required:
    'Mappings or expected windows differ from the approved profile. Review and approve those changes first.',
  expected_inventory_count_mismatch:
    'The independently expected room/building counts must match the reviewed inventory. Check for missing or extra rooms.',
  incomplete_timetable_window:
    'Observed rows do not match reviewed expected coverage. Resolve partial exports or explicitly review a changed room window.',
  source_capacity_changed:
    'A source capacity differs from the approved expectation. Review the difference before changing the profile.',
  manifest_review_required:
    'Sources changed or the generated draft has not been reviewed. Analyze, confirm metadata, and validate again.',
  target_confirmation_required: 'Confirm the target dates, year and source-file mappings.',
  capture_confirmation_required: 'Confirm actual capture timestamps for every original export.',
  future_capture_time: 'A capture timestamp is in the future. Check its date and UTC offset.',
  unresolved_local_time:
    'The timetable touches an unresolved Toronto DST gap or repeated hour. This source cannot safely establish that interval.',
  invalid_request:
    'Check the reviewed fields, required identities and timezone-aware capture timestamps.',
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
        errorHelp[result.error?.code] ?? '',
        ...(result.error?.report?.anomalies ?? []),
        ...(result.error?.report?.missing ?? []),
      ]
        .filter(Boolean)
        .join(': '),
    )
  return result as T
}

export interface InventoryWindow {
  start: string
  end: string
}
export interface InventoryRoom {
  source_name: string
  room_number: string
  source_id: number | null
  capacity: number | null
  window?: InventoryWindow | null
}
export interface InventoryBuilding {
  source_name: string
  code: string
  name: string
  rooms: InventoryRoom[]
}
export interface Inventory {
  source_formats: ('daily' | 'weekly')[]
  window: InventoryWindow
  buildings: InventoryBuilding[]
}
export interface InventoryProfile extends Inventory {
  version: number
  reviewed_at: string
  review_reason: string
  expected_rooms: number
  expected_buildings: number
}
export interface ManifestSource {
  file: string
  fetched_at: string
  date?: string
  week_start?: string
}
export interface ManifestDraft {
  version: number
  source_format: 'daily' | 'weekly'
  start_date: string
  window: InventoryWindow
  buildings: InventoryBuilding[]
  inventory_scope?: 'complete'
  inventory_review_reason?: string
  weeks?: ManifestSource[]
  snapshots?: ManifestSource[]
}
export interface SourceAnalysis {
  observed_rooms: {
    source_building: string | null
    source_name: string
    source_id: number | null
    capacity: number
    window: InventoryWindow
    row_minutes: number[]
  }[]
  analysis_hash: string
  source_format: 'daily' | 'weekly'
  start_date: string
  profile_version: number
  bootstrap_required: boolean
  missing_sources: string[]
  files: {
    file: string
    bytes: number
    sha256: string
    period: string
    format: string
    rooms: number
    dates: string[]
    row_steps: number[]
  }[]
  draft: ManifestDraft
  summary: { rooms: number; buildings: number; occurrences: number; dates: string[] }
  issues: { code: string; severity: string; room?: string; file?: string }[]
  differences: {
    added_rooms: string[]
    missing_rooms: string[]
    unmatched_rooms: string[]
    capacity_changes: { room: string; expected: number; observed: number }[]
    window_changes: { room: string; expected: InventoryWindow; observed: InventoryWindow }[]
    source_id_changes: { room: string; expected: number; observed: number }[]
  }
}
