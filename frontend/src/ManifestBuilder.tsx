import { useEffect, useState } from 'react'
import { DatePicker, Select } from './Controls.tsx'
import { InventoryEditor } from './InventoryEditor.tsx'
import { campusDate } from './time.ts'
import { opsRequest } from './operator-api.ts'
import type {
  Inventory,
  InventoryProfile,
  ManifestDraft,
  Preview,
  SourceAnalysis,
} from './operator-api.ts'

const inventoryOf = (draft: ManifestDraft, formats: Inventory['source_formats']): Inventory => ({
  source_formats: formats,
  window: draft.window,
  buildings: draft.buildings,
})
const signature = (value: Inventory) =>
  JSON.stringify({
    formats: [...value.source_formats].sort(),
    window: value.window,
    buildings: value.buildings.map((b) => ({
      source_name: b.source_name,
      code: b.code,
      name: b.name,
      rooms: b.rooms.map((r) => ({
        source_name: r.source_name,
        room_number: r.room_number,
        source_id: r.source_id ?? null,
        capacity: r.capacity ?? null,
        window: r.window ?? null,
      })),
    })),
  })
const download = (name: string, value: unknown) => {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }),
  )
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}
function readDraft(text: string): ManifestDraft {
  const v = JSON.parse(text)
  if (
    !v ||
    (v.weeks !== undefined && !Array.isArray(v.weeks)) ||
    (v.snapshots !== undefined && !Array.isArray(v.snapshots))
  )
    throw new Error('Choose a valid daily/weekly manifest object.')
  if (Array.isArray(v.snapshots))
    v.snapshots = v.snapshots.map(
      (source: Record<string, unknown>) =>
        source && { ...source, file: source.file ?? `${source.date}.html` },
    )
  const windowOK = (w: unknown) =>
    !!w &&
    typeof w === 'object' &&
    typeof (w as Record<string, unknown>).start === 'string' &&
    typeof (w as Record<string, unknown>).end === 'string'
  if (
    !v ||
    !['daily', 'weekly'].includes(v.source_format) ||
    typeof v.start_date !== 'string' ||
    !windowOK(v.window) ||
    !Array.isArray(v.buildings) ||
    v.buildings.some(
      (b: Record<string, unknown>) =>
        !b ||
        typeof b.source_name !== 'string' ||
        typeof b.code !== 'string' ||
        typeof b.name !== 'string' ||
        !Array.isArray(b.rooms) ||
        b.rooms.some(
          (r: Record<string, unknown>) =>
            !r ||
            typeof r.source_name !== 'string' ||
            typeof r.room_number !== 'string' ||
            (r.capacity != null && typeof r.capacity !== 'number') ||
            (r.source_id != null && typeof r.source_id !== 'number') ||
            (r.window != null && !windowOK(r.window)),
        ),
    ) ||
    ![...(v.weeks ?? []), ...(v.snapshots ?? [])].every(
      (s) => s && typeof s.file === 'string' && typeof s.fetched_at === 'string',
    )
  )
    throw new Error(
      'Manifest structure is invalid. Use the generated draft or load a complete daily/weekly manifest.',
    )
  return v
}

export function ManifestBuilder({
  csrf,
  busy,
  locked,
  run,
  onPrepared,
  onInvalidate,
  onDiscard,
  onExpired,
}: {
  csrf: string
  busy: boolean
  locked: boolean
  run: (task: () => Promise<void>) => Promise<void>
  onPrepared: (result: { batch: string; preview: Preview; reason: string }) => void
  onInvalidate: () => void
  onDiscard: () => void
  onExpired: () => void
}) {
  const [start, setStart] = useState(campusDate(new Date()))
  const [format, setFormat] = useState('auto')
  const [files, setFiles] = useState<File[]>([])
  const [batch, setBatch] = useState('')
  const [analysis, setAnalysis] = useState<SourceAnalysis | null>(null)
  const [draft, setDraft] = useState<ManifestDraft | null>(null)
  const [profile, setProfile] = useState<InventoryProfile | null>(null)
  const [profilePending, setProfilePending] = useState(true)
  const [profileError, setProfileError] = useState('')
  const [editingProfile, setEditingProfile] = useState<Inventory | null>(null)
  const [formats, setFormats] = useState<Inventory['source_formats']>(['weekly'])
  const [expectedRooms, setExpectedRooms] = useState('')
  const [expectedBuildings, setExpectedBuildings] = useState('')
  const [reason, setReason] = useState('')
  const [independentAck, setIndependentAck] = useState(false)
  const [captureAck, setCaptureAck] = useState(false)
  const [targetAck, setTargetAck] = useState(false)
  const [captures, setCaptures] = useState<Record<string, string>>({})
  const [captureEvidence, setCaptureEvidence] = useState<Record<string, string>>({})
  const [raw, setRaw] = useState('')
  const [notice, setNotice] = useState('')
  const [validated, setValidated] = useState(false)
  const [fileError, setFileError] = useState('')
  useEffect(() => {
    let alive = true
    opsRequest<{ profile: InventoryProfile | null }>('inventory-profile', csrf)
      .then((result) => {
        if (!alive) return
        setProfile(result.profile)
        if (result.profile) {
          setExpectedRooms(String(result.profile.expected_rooms))
          setExpectedBuildings(String(result.profile.expected_buildings))
          setReason(result.profile.review_reason)
          setFormats(result.profile.source_formats)
        }
      })
      .catch((e) => {
        if (alive) {
          setProfileError(e.message.replaceAll('_', ' '))
          if (e.message.includes('authentication_required')) onExpired()
        }
      })
      .finally(() => {
        if (alive) setProfilePending(false)
      })
    return () => {
      alive = false
    }
  }, [csrf, onExpired])
  const invalidate = () => {
    setValidated(false)
    setIndependentAck(false)
    setNotice('')
    onInvalidate()
  }
  const invalidateAnalysis = () => {
    invalidate()
    setAnalysis(null)
    setDraft(null)
    setCaptureAck(false)
    setTargetAck(false)
    setCaptures({})
    setCaptureEvidence({})
  }
  const updateDraft = (next: ManifestDraft) => {
    setDraft(next)
    setRaw(JSON.stringify(next, null, 2))
    invalidate()
  }
  const accept = (incoming: File[]) => {
    if (busy || locked) return
    const merged = new Map(files.map((file) => [file.name, file]))
    for (const file of incoming) {
      if (!/\.html$/i.test(file.name) || file.size > 10 * 1024 * 1024) {
        setFileError('Choose HTML exports no larger than 10 MB each.')
        return
      }
      merged.set(file.name, file)
    }
    if (merged.size > 7) {
      setFileError('Choose at most seven daily exports, or the one or two required weekly exports.')
      return
    }
    setFiles([...merged.values()])
    setFileError('')
    invalidateAnalysis()
  }
  const storedName = (file: File, index: number) =>
    /^[A-Za-z0-9][A-Za-z0-9._-]{0,100}\.html$/.test(file.name)
      ? file.name
      : `source-${index + 1}.html`
  const applyAnalysis = (result: SourceAnalysis, approved = profile) => {
    setAnalysis(result)
    setDraft(result.draft)
    setRaw(JSON.stringify(result.draft, null, 2))
    setFormats(
      approved?.source_formats.includes(result.source_format)
        ? approved.source_formats
        : [result.source_format],
    )
    setValidated(false)
    onInvalidate()
  }
  async function analyze() {
    if (!files.length) throw new Error('Choose at least one authorized timetable export.')
    const names = files.map(storedName)
    if (new Set(names).size !== names.length)
      throw new Error(
        'Uploaded filenames conflict after safe storage naming. Rename one file and try again.',
      )
    const latest = await opsRequest<{ profile: InventoryProfile | null }>('inventory-profile', csrf)
    setProfile(latest.profile)
    setProfileError('')
    if (latest.profile && latest.profile.version !== profile?.version) {
      setExpectedRooms(String(latest.profile.expected_rooms))
      setExpectedBuildings(String(latest.profile.expected_buildings))
      setIndependentAck(false)
    }
    if (batch) await opsRequest(`batches/${batch}`, csrf, 'DELETE')
    const next = await opsRequest<{ batch_id: string }>('batches', csrf, 'POST')
    setBatch(next.batch_id)
    for (const [index, file] of files.entries())
      await opsRequest(`batches/${next.batch_id}/files/${names[index]}`, csrf, 'PUT', file)
    const result = await opsRequest<SourceAnalysis>(
      `batches/${next.batch_id}/analyze`,
      csrf,
      'POST',
      { start_date: start, ...(format === 'auto' ? {} : { source_format: format }) },
    )
    applyAnalysis(result, latest.profile)
    setCaptureAck(false)
    setTargetAck(false)
    setNotice(
      'Sources analyzed. No database records were written. Review inventory and actual capture timestamps.',
    )
  }
  const currentInventory = draft ? inventoryOf(draft, formats) : null
  const matches =
    !!profile && !!currentInventory && signature(currentInventory) === signature(profile)
  async function saveProfile(value: Inventory) {
    if (!independentAck)
      throw new Error(
        'Independently review expected inventory and coverage before approving a profile.',
      )
    const result = await opsRequest<{ profile: InventoryProfile }>(
      'inventory-profile',
      csrf,
      'PUT',
      {
        ...value,
        expected_version: profile?.version ?? 0,
        expected_rooms: Number(expectedRooms),
        expected_buildings: Number(expectedBuildings),
        review_reason: reason,
        review_acknowledged: independentAck,
      },
    )
    setProfile(result.profile)
    setEditingProfile(null)
    setIndependentAck(false)
    invalidate()
    if (batch && analysis) {
      const next = await opsRequest<SourceAnalysis>(`batches/${batch}/analyze`, csrf, 'POST', {
        start_date: start,
      })
      setAnalysis(next)
      setDraft(next.draft)
      setRaw(JSON.stringify(next.draft, null, 2))
      setFormats(result.profile.source_formats)
    }
    setNotice(
      `Approved inventory profile v${result.profile.version} saved privately. Published data has not changed.`,
    )
  }
  async function validate() {
    if (!draft || !analysis) throw new Error('Analyze the uploaded sources first.')
    if (!profile || !matches)
      throw new Error('Approve the reviewed inventory profile before validating this manifest.')
    if (!targetAck) throw new Error('Review the target dates, year and source-file mappings.')
    if (!captureAck)
      throw new Error('Confirm the actual capture timestamp for each original export.')
    if (analysis.missing_sources.length)
      throw new Error(`Additional sources required: ${analysis.missing_sources.join(', ')}.`)
    const reviewed = {
      ...draft,
      ...(draft.source_format === 'weekly' ? { inventory_review_reason: reason } : {}),
      ...(draft.source_format === 'weekly'
        ? {
            weeks: draft.weeks?.map((s) => ({
              ...s,
              fetched_at: captures[s.file] ?? s.fetched_at,
              capture_evidence: captureEvidence[s.file] ?? s.capture_evidence,
            })),
          }
        : {
            snapshots: draft.snapshots?.map((s) => ({
              ...s,
              fetched_at: captures[s.file] ?? s.fetched_at,
              capture_evidence: captureEvidence[s.file] ?? s.capture_evidence,
            })),
          }),
    }
    if ((reviewed.weeks ?? reviewed.snapshots ?? []).some((s) => !s.fetched_at))
      throw new Error(
        'Enter an actual capture timestamp for every export; upload time is not a substitute.',
      )
    const saved = await opsRequest<{ manifest: ManifestDraft }>(
      `batches/${batch}/manifest`,
      csrf,
      'POST',
      {
        analysis_hash: analysis.analysis_hash,
        profile_version: profile.version,
        manifest: reviewed,
        review_reason: reason,
        review_acknowledged: true,
        capture_acknowledged: captureAck,
        target_acknowledged: targetAck,
      },
    )
    setDraft(saved.manifest)
    setRaw(JSON.stringify(saved.manifest, null, 2))
    const preview = await opsRequest<Preview>(`batches/${batch}/preview`, csrf, 'POST')
    setValidated(true)
    onPrepared({ batch, preview, reason })
    setNotice('Manifest validated and compared. Nothing is staged or published yet.')
  }
  const approvalControls = (value: Inventory) => (
    <div className="ops-profile-approval">
      <fieldset disabled={busy || locked} className="ops-editor-fields">
        <legend>Profile compatibility</legend>
        {(['weekly', 'daily'] as const).map((kind) => (
          <label className="ops-check" key={kind}>
            <input
              type="checkbox"
              checked={value.source_formats.includes(kind)}
              onChange={(e) => {
                const next = {
                  ...value,
                  source_formats: e.target.checked
                    ? [...value.source_formats, kind]
                    : value.source_formats.filter((f) => f !== kind),
                }
                if (editingProfile) setEditingProfile(next)
                else setFormats(next.source_formats)
                invalidate()
              }}
            />
            {kind === 'weekly' ? 'Weekly exports' : 'Daily exports'}
          </label>
        ))}
      </fieldset>
      <p className="notice warning">
        Establish expected inventory independently of the uploaded rows. Parsing an export does not
        prove that the full campus inventory or every room window is complete.
      </p>
      <div className="ops-editor-fields">
        <label>
          Independently expected rooms
          <input
            type="number"
            min={1}
            value={expectedRooms}
            disabled={busy || locked}
            onChange={(e) => {
              setExpectedRooms(e.target.value)
              setIndependentAck(false)
            }}
          />
        </label>
        <label>
          Independently expected buildings
          <input
            type="number"
            min={1}
            value={expectedBuildings}
            disabled={busy || locked}
            onChange={(e) => {
              setExpectedBuildings(e.target.value)
              setIndependentAck(false)
            }}
          />
        </label>
      </div>
      <label className="ops-check">
        <input
          type="checkbox"
          disabled={busy || locked}
          checked={independentAck}
          onChange={(e) => setIndependentAck(e.target.checked)}
        />
        I independently verified the expected inventory and coverage; parsed rows alone are not
        proof.
      </label>
      <button
        type="button"
        className="button secondary"
        disabled={busy || locked || !independentAck}
        onClick={() => void run(() => saveProfile(value))}
      >
        Approve inventory profile
      </button>
    </div>
  )
  const step = locked ? 5 : validated ? 4 : analysis ? 3 : files.length ? 2 : 1
  return (
    <div className="ops-builder">
      <ol className="ops-progress" aria-label="Import progress">
        {['Upload', 'Analyze', 'Review', 'Validate', 'Stage & publish'].map((label, index) => (
          <li key={label} aria-current={step === index + 1 ? 'step' : undefined}>
            {index + 1}. {label}
          </li>
        ))}
      </ol>
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      {locked && (
        <p className="notice warning">
          Candidate inputs are locked. Discard uploads to start another import; audited datasets are
          retained.
        </p>
      )}
      <details className="ops-card">
        <summary>
          Approved inventory profile {profile ? `v${profile.version}` : '— bootstrap required'}
        </summary>
        {profilePending ? (
          <p role="status">Loading approved inventory…</p>
        ) : profileError ? (
          <p role="alert">{profileError}</p>
        ) : profile ? (
          <>
            <p>
              {profile.expected_rooms} expected rooms · {profile.expected_buildings} buildings ·
              reviewed {profile.reviewed_at}
            </p>
            <p>Review: {profile.review_reason}. Saving a profile never publishes a dataset.</p>
            <div className="ops-actions">
              <button
                type="button"
                className="button secondary"
                disabled={busy || locked}
                onClick={() => {
                  setEditingProfile({
                    source_formats: profile.source_formats,
                    window: profile.window,
                    buildings: structuredClone(profile.buildings),
                  })
                  setIndependentAck(false)
                }}
              >
                Edit approved profile
              </button>
              <button
                type="button"
                className="button secondary"
                onClick={() => download(`intervella-inventory-v${profile.version}.json`, profile)}
              >
                Export approved profile
              </button>
            </div>
          </>
        ) : (
          <p>
            No inventory is approved. Analyze an export to create a draft, then independently
            establish expected rooms and coverage before approving it.
          </p>
        )}
        <label>
          Load reviewed profile or manifest
          <input
            type="file"
            accept=".json,application/json"
            disabled={busy || locked}
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file)
                void run(async () => {
                  if (file.size > 1024 * 1024)
                    throw new Error('Profile or manifest must be smaller than 1 MB.')
                  const source = JSON.parse(await file.text())
                  const detected =
                    source.source_format ??
                    source.source_formats?.[0] ??
                    (source.version === 1 || Array.isArray(source.snapshots)
                      ? 'daily'
                      : source.version === 2 || Array.isArray(source.weeks)
                        ? 'weekly'
                        : null)
                  if (!detected)
                    throw new Error(
                      'Profile compatibility or daily/weekly manifest format is required.',
                    )
                  const value = readDraft(
                    JSON.stringify({
                      ...source,
                      source_format: detected,
                      start_date: source.start_date ?? start,
                    }),
                  )
                  const compatible = source.source_formats ?? [value.source_format]
                  if (
                    !Array.isArray(compatible) ||
                    compatible.some((v) => !['daily', 'weekly'].includes(v))
                  )
                    throw new Error('Choose a valid daily/weekly inventory profile.')
                  setEditingProfile(inventoryOf(value, compatible))
                  setExpectedRooms(source.expected_rooms ? String(source.expected_rooms) : '')
                  setExpectedBuildings(
                    source.expected_buildings ? String(source.expected_buildings) : '',
                  )
                  invalidate()
                  setNotice(
                    'Loaded configuration is a draft only. Independently review it before approving a profile.',
                  )
                })
            }}
          />
        </label>
        {editingProfile && (
          <>
            <InventoryEditor
              value={editingProfile}
              date={start}
              disabled={busy || locked}
              onChange={(v) => {
                setEditingProfile(v)
                invalidate()
              }}
            />
            <label>
              Profile review reason
              <input
                value={reason}
                disabled={busy || locked}
                maxLength={64}
                onChange={(e) => {
                  setReason(e.target.value)
                  setIndependentAck(false)
                }}
              />
            </label>
            {approvalControls(editingProfile)}
            <button type="button" className="text-button" onClick={() => setEditingProfile(null)}>
              Cancel profile edits
            </button>
          </>
        )}
      </details>
      <div className="ops-card">
        <h3>1. Upload authorized exports</h3>
        <p>
          Choose or drop the original daily or weekly HTML. Source descriptions stay private and are
          never shown in this review.
        </p>
        <fieldset disabled={busy || locked} className="ops-editor-fields">
          <label>
            Target start date
            <DatePicker
              label="Target start date"
              value={start}
              onChange={(v) => {
                setStart(v)
                invalidateAnalysis()
              }}
            />
          </label>
          <label>
            Source format
            <Select
              label="Source format"
              value={format}
              onChange={(v) => {
                setFormat(v)
                invalidateAnalysis()
              }}
            >
              <option value="auto">Detect from HTML</option>
              <option value="weekly">Weekly exports</option>
              <option value="daily">Daily exports</option>
            </Select>
          </label>
        </fieldset>
        <div
          className="ops-dropzone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            accept([...e.dataTransfer.files])
          }}
        >
          <label>
            Authorized HTML exports
            <input
              type="file"
              accept=".html,text/html"
              multiple
              disabled={busy || locked}
              onChange={(e) => accept([...(e.target.files ?? [])])}
            />
          </label>
          <p className="small">
            Up to seven files, 10 MB each. One Sunday–Saturday week covers a Sunday start; other
            seven-day windows need two adjacent weekly exports. Daily imports need seven dated
            exports.
          </p>
        </div>
        {fileError && (
          <p role="alert" className="form-error">
            {fileError}
          </p>
        )}
        {!files.length ? (
          <p className="small">No exports selected.</p>
        ) : (
          <ul className="ops-source-list">
            {files.map((file, index) => (
              <li key={file.name}>
                <strong>{file.name}</strong> · {Math.ceil(file.size / 1024)} KB{' '}
                {storedName(file, index) !== file.name && (
                  <span>· Stored as {storedName(file, index)}</span>
                )}
                <button
                  type="button"
                  className="text-button"
                  disabled={busy || locked}
                  onClick={() => {
                    setFiles(files.filter((f) => f !== file))
                    invalidateAnalysis()
                  }}
                  aria-label={`Remove export ${file.name}`}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
        <h3>2. Analyze sources</h3>
        <div className="ops-actions">
          <button
            type="button"
            className="button primary"
            disabled={busy || locked || !files.length || profilePending || !!profileError}
            onClick={() => void run(analyze)}
          >
            {busy ? 'Working…' : 'Analyze & generate draft'}
          </button>
          {batch && (
            <button
              type="button"
              className="button secondary"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  await opsRequest(`batches/${batch}`, csrf, 'DELETE')
                  setBatch('')
                  setAnalysis(null)
                  setDraft(null)
                  setFiles([])
                  setCaptureAck(false)
                  setValidated(false)
                  onDiscard()
                  setNotice(
                    'Private uploads discarded. Audited datasets and approved inventory are retained.',
                  )
                })
              }
            >
              Discard uploads
            </button>
          )}
        </div>
      </div>
      {analysis && draft && currentInventory && (
        <section className="ops-card ops-generated-review" aria-labelledby="manifest-review-title">
          <h3 id="manifest-review-title">3. Review generated manifest</h3>
          <p>
            <strong>
              {analysis.source_format === 'weekly' ? 'Weekly' : 'Daily'} timetable detected.
            </strong>{' '}
            {analysis.summary.buildings} building groups · {analysis.summary.rooms} rooms ·{' '}
            {analysis.summary.occurrences} meeting occurrences.
          </p>
          <p>
            Seven-day target: {analysis.summary.dates[0]} through {analysis.summary.dates.at(-1)}.{' '}
            {matches
              ? `Mappings match approved profile v${profile?.version}.`
              : 'Inventory approval or correction is required.'}
          </p>
          {analysis.missing_sources.length > 0 && (
            <p className="notice warning" role="status">
              Additional {analysis.source_format === 'weekly' ? 'weekly exports' : 'daily exports'}{' '}
              required: {analysis.missing_sources.join(', ')}.{' '}
              {analysis.source_format === 'weekly'
                ? 'This period crosses a Sunday boundary; upload both enclosing weeks.'
                : 'Every target calendar date needs its own structurally complete export.'}
            </p>
          )}
          <label className="ops-check">
            <input
              type="checkbox"
              disabled={busy || locked}
              checked={targetAck}
              onChange={(e) => setTargetAck(e.target.checked)}
            />
            I reviewed the target dates, year and source-file mappings.
          </label>
          <div className="ops-differences" aria-label="Inventory changes">
            <p>
              <strong>{analysis.differences.added_rooms.length}</strong> unfamiliar rooms ·{' '}
              <strong>{analysis.differences.missing_rooms.length}</strong> missing expected rooms ·{' '}
              <strong>{analysis.differences.capacity_changes.length}</strong> capacity changes ·{' '}
              <strong>{analysis.differences.window_changes.length}</strong> window changes.
            </p>
            <details>
              <summary>Inspect inventory differences and review obligations</summary>
              <p>
                Compared with{' '}
                {analysis.profile_version
                  ? `profile v${analysis.profile_version}`
                  : 'no approved inventory'}
                . An unmatched label may be a rename; resolve canonical identity explicitly.
              </p>
              <p>Unfamiliar: {analysis.differences.added_rooms.join(', ') || 'None'}</p>
              <p>Missing: {analysis.differences.missing_rooms.join(', ') || 'None'}</p>
              {analysis.differences.capacity_changes.map((c) => (
                <p key={c.room}>
                  {c.room}: expected {c.expected} seats, observed {c.observed}.
                </p>
              ))}
              {analysis.differences.window_changes.map((c) => (
                <p key={c.room}>
                  {c.room}: expected {c.expected.start}–{c.expected.end}, observed{' '}
                  {c.observed.start}–{c.observed.end}.
                </p>
              ))}
              {analysis.differences.source_id_changes.map((c) => (
                <p key={c.room}>
                  {c.room}: approved source ID {c.expected}, observed {c.observed}. Review the
                  locator; this is not the database ID.
                </p>
              ))}
              <ul>
                {analysis.issues.map((issue, i) => (
                  <li key={i}>
                    {issue.severity === 'blocking' ? 'Blocking' : 'Confirm'}:{' '}
                    {issue.code.replaceAll('_', ' ')}
                    {issue.room && ` · ${issue.room}`}
                    {issue.file && ` · ${issue.file}`}
                  </li>
                ))}
              </ul>
            </details>
          </div>
          <fieldset disabled={busy || locked} className="ops-source-metadata">
            <legend>Original source metadata</legend>
            {analysis.files.map((file) => (
              <div className="ops-upload" key={file.file}>
                <strong>{file.file}</strong>
                <p className="small">
                  {file.format === 'weekly' ? 'Week beginning' : 'Date'} {file.period} ·{' '}
                  {file.rooms} rooms · observed row increments {file.row_steps.join(', ')} minutes
                </p>
                <details>
                  <summary>Source hash and date mapping</summary>
                  <p className="ops-hash">SHA-256 {file.sha256}</p>
                  <p>{file.dates.join(', ')}</p>
                </details>
                <label>
                  Actual capture timestamp for {file.file}
                  <input
                    value={
                      captures[file.file] ??
                      (draft.weeks ?? draft.snapshots ?? []).find((s) => s.file === file.file)
                        ?.fetched_at ??
                      ''
                    }
                    placeholder="YYYY-MM-DDTHH:MM:SS-04:00"
                    onChange={(e) => {
                      setCaptures({ ...captures, [file.file]: e.target.value })
                      setCaptureAck(false)
                      invalidate()
                    }}
                  />
                </label>
                <p className="small">
                  Include the actual UTC offset. File date, modification time, upload time and the
                  current clock are not capture evidence.
                </p>
                <label>Capture evidence reference for {file.file}
                  <input maxLength={500} value={captureEvidence[file.file] ??
                    (draft.weeks ?? draft.snapshots ?? []).find((s) => s.file === file.file)?.capture_evidence ?? ''}
                    onChange={(e) => {
                      setCaptureEvidence({ ...captureEvidence, [file.file]: e.target.value })
                      setCaptureAck(false)
                      invalidate()
                    }} />
                </label>
              </div>
            ))}
            <label className="ops-check">
              <input
                type="checkbox"
                checked={captureAck}
                onChange={(e) => setCaptureAck(e.target.checked)}
              />
              I confirm these are the actual capture timestamps for the original exports.
            </label>
          </fieldset>
          <InventoryEditor
            value={currentInventory}
            date={start}
            disabled={busy || locked}
            onChange={(v) => {
              setFormats(v.source_formats)
              updateDraft({ ...draft, window: v.window, buildings: v.buildings })
            }}
          />
          <label>
            Review reason (short code)
            <input
              value={reason}
              disabled={busy || locked}
              maxLength={64}
              placeholder="weekly-inventory-reviewed"
              pattern="[a-z][a-z0-9_-]{0,63}"
              onChange={(e) => {
                setReason(e.target.value)
                invalidate()
              }}
            />
          </label>
          {!matches && approvalControls(currentInventory)}
          <details
            className="ops-advanced"
            onToggle={(e) => {
              if (e.currentTarget.open)
                setRaw(
                  JSON.stringify(
                    {
                      ...draft,
                      ...(draft.source_format === 'weekly'
                        ? {
                            weeks: draft.weeks?.map((s) => ({
                              ...s,
                              fetched_at: captures[s.file] ?? s.fetched_at,
                            })),
                          }
                        : {
                            snapshots: draft.snapshots?.map((s) => ({
                              ...s,
                              fetched_at: captures[s.file] ?? s.fetched_at,
                            })),
                          }),
                    },
                    null,
                    2,
                  ),
                )
            }}
          >
            <summary>Advanced: inspect, edit or download manifest JSON</summary>
            <p>
              Raw edits remain subject to the same source, inventory, capture and coverage checks.
              Change the target period above and reanalyze if needed.
            </p>
            <label>
              Generated manifest JSON
              <textarea
                rows={12}
                maxLength={1024 * 1024}
                value={raw}
                disabled={busy || locked}
                spellCheck={false}
                onChange={(e) => setRaw(e.target.value)}
              />
            </label>
            <div className="ops-actions">
              <button
                type="button"
                className="button secondary"
                disabled={busy || locked}
                onClick={() =>
                  void run(async () => {
                    const next = readDraft(raw)
                    if (next.start_date !== start || next.source_format !== analysis.source_format)
                      throw new Error(
                        'Change the target date or detected format above and analyze again before editing its manifest.',
                      )
                    updateDraft(next)
                    setCaptures(
                      Object.fromEntries(
                        (next.weeks ?? next.snapshots ?? []).map((s) => [s.file, s.fetched_at]),
                      ),
                    )
                    setCaptureAck(false)
                  })
                }
              >
                Apply JSON edits to draft
              </button>
              <button
                type="button"
                className="button secondary"
                onClick={() =>
                  void run(async () =>
                    download(`intervella-manifest-${start}.json`, readDraft(raw)),
                  )
                }
              >
                Download manifest JSON
              </button>
            </div>
          </details>
          <button
            type="button"
            className="button primary"
            disabled={
              busy ||
              locked ||
              !matches ||
              !captureAck ||
              !targetAck ||
              !!analysis.missing_sources.length ||
              analysis.issues.some((i) => i.severity === 'blocking')
            }
            onClick={() => void run(validate)}
          >
            Validate & compare (no database writes)
          </button>
        </section>
      )}
    </div>
  )
}
