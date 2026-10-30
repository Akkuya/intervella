import { useState } from 'react'
import { opsRequest } from './operator-api.ts'
import type { InventoryProfile, ManifestDraft, OpsHealth, Preview, SourceAnalysis } from './operator-api.ts'

interface Week {
  start_date: string
  batch_id?: string
  analysis?: SourceAnalysis
  blocking: string[]
  files: { file: string; format: string; period: string; date_evidence: string }[]
  draft?: ManifestDraft
  preview?: Preview
  candidate?: string
  selected: boolean
}
interface Discovery {
  groups: Week[]
  exceptions: { file: string; code: string }[]
  profile: InventoryProfile | null
}

const adjusted = (analysis: SourceAnalysis): ManifestDraft => {
  const draft = structuredClone(analysis.draft)
  const blocked = analysis.missing_sources.length > 0 || analysis.issues.some((i) => i.severity === 'blocking')
  if (blocked) return draft
  for (const building of draft.buildings)
    for (const room of building.rooms) {
      const observed = analysis.observed_rooms.find((r) => r.source_name === room.source_name &&
        (analysis.source_format === 'weekly' || r.source_building === building.source_name))
      if (observed?.bulk_eligible && JSON.stringify(observed.window) !== JSON.stringify(room.window ?? draft.window) && observed.capacity === room.capacity &&
          (analysis.source_format === 'weekly' || observed.source_id === room.source_id))
        room.window = observed.window
    }
  return draft
}

export function MultiweekImporter({ csrf, busy, run, onHealth }: {
  csrf: string
  busy: boolean
  run: (task: () => Promise<void>) => Promise<void>
  onHealth: (health: OpsHealth) => void
}) {
  const [parent, setParent] = useState('')
  const [files, setFiles] = useState<{ name: string; original: string }[]>([])
  const [year, setYear] = useState('')
  const [years, setYears] = useState<Record<string, string>>({})
  const [weeks, setWeeks] = useState<Week[]>([])
  const [exceptions, setExceptions] = useState<Discovery['exceptions']>([])
  const [profile, setProfile] = useState<InventoryProfile | null>(null)
  const [captures, setCaptures] = useState<Record<string, string>>({})
  const [evidence, setEvidence] = useState<Record<string, string>>({})
  const [reason, setReason] = useState('')
  const [reviewed, setReviewed] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [baseline, setBaseline] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const [discoveryDirty, setDiscoveryDirty] = useState(false)
  const locked = weeks.some((w) => !!w.candidate)
  const update = (start: string, change: Partial<Week>) =>
    setWeeks((current) => current.map((w) => w.start_date === start ? { ...w, ...change } : w))
  const invalidate = () => {
    setReviewed(false)
    setConfirm(false)
    setWeeks((current) => current.map((w) => w.candidate ? w : { ...w, preview: undefined }))
  }
  async function discover(batch = parent) {
    const result = await opsRequest<Discovery>(`batches/${batch}/discover`, csrf, 'POST', {
      ...(year ? { year: Number(year) } : {}),
      years: Object.fromEntries(Object.entries(years).filter(([, v]) => v).map(([k, v]) => [k, Number(v)])),
      original_names: Object.fromEntries(files.map((f) => [f.name, f.original])),
    })
    setProfile(result.profile)
    setExceptions(result.exceptions)
    setWeeks(result.groups.map((w) => ({ ...w, selected: !w.blocking.length,
      draft: w.analysis ? adjusted(w.analysis) : undefined })))
    setReviewed(false)
    setConfirm(false)
    setDiscoveryDirty(false)
    setNotice('Detected weeks are ready for review. Missing years, capture evidence and other exceptions remain visible.')
  }
  async function accept(incoming: File[]) {
    if (!incoming.length || busy || locked) return
    if (incoming.length > 84 || incoming.some((f) => !/\.html$/i.test(f.name) || f.size > 10 * 1024 * 1024) ||
        incoming.reduce((size, f) => size + f.size, 0) > 100 * 1024 * 1024)
      throw new Error('Choose up to 84 HTML exports, at most 10 MB each and 100 MB total.')
    if (parent) await opsRequest(`batches/${parent}`, csrf, 'DELETE')
    setWeeks([])
    setExceptions([])
    setCaptures({})
    setEvidence({})
    setConfirm(false)
    const next = await opsRequest<{ batch_id: string }>('batches', csrf, 'POST')
    setParent(next.batch_id)
    const stored = incoming.map((f, i) => ({ name: `source-${i + 1}.html`, original: f.name }))
    setFiles(stored)
    setYears({})
    for (const [i, file] of incoming.entries())
      await opsRequest(`batches/${next.batch_id}/files/${stored[i].name}`, csrf, 'PUT', file)
    // A new selection has no inherited per-file year overrides.
    const result = await opsRequest<Discovery>(`batches/${next.batch_id}/discover`, csrf, 'POST',
      { ...(year ? { year: Number(year) } : {}),
        original_names: Object.fromEntries(stored.map((f) => [f.name, f.original])) })
    setProfile(result.profile)
    setExceptions(result.exceptions)
    setWeeks(result.groups.map((w) => ({ ...w, selected: !w.blocking.length,
      draft: w.analysis ? adjusted(w.analysis) : undefined })))
    setReviewed(false)
    setDiscoveryDirty(false)
    setNotice('Sources detected and grouped locally. Review the proposed windows and original capture evidence.')
  }
  const selected = weeks.filter((w) => w.selected)
  const sources = [...new Set(weeks.flatMap((w) => w.files.map((f) => f.file)))]
  const label = (name: string) => files.find((f) => f.name === name)?.original ?? name
  async function validateWeeks() {
    if (discoveryDirty || !reviewed || !reason || !profile || !selected.length)
      throw new Error('Review selected weeks, mappings, windows, dates and capture evidence first.')
    for (const week of selected) {
      if (week.candidate) continue
      const a = week.analysis
      if (!a || !week.draft || !week.batch_id || week.blocking.length || a.missing_sources.length)
        throw new Error(`Resolve the exceptions for ${week.start_date} before staging.`)
      const withCapture = (s: NonNullable<ManifestDraft['weeks']>[number]) => ({ ...s,
        fetched_at: captures[s.file] ?? s.fetched_at,
        capture_evidence: evidence[s.file] ?? s.capture_evidence,
      })
      const draft: ManifestDraft = { ...week.draft,
        ...(week.draft.source_format === 'weekly'
          ? { weeks: week.draft.weeks?.map(withCapture), inventory_review_reason: reason }
          : { snapshots: week.draft.snapshots?.map(withCapture) }),
      }
      if ((draft.weeks ?? draft.snapshots ?? []).some((s) => !s.fetched_at || !s.capture_evidence?.trim()))
        throw new Error('Every source needs an actual offset-aware capture timestamp and its evidence reference.')
      await opsRequest(`batches/${week.batch_id}/manifest`, csrf, 'POST', {
        analysis_hash: a.analysis_hash, profile_version: profile.version, manifest: draft,
        review_reason: reason, review_acknowledged: true, windows_acknowledged: true,
        capture_acknowledged: true, target_acknowledged: true,
      })
      const preview = await opsRequest<Preview>(`batches/${week.batch_id}/preview`, csrf, 'POST')
      // Show comparisons before permitting a separate stage action.
      update(week.start_date, { preview })
    }
    setNotice('Validation complete. Review the comparisons below, then stage the selected weeks.')
    setReviewed(false)
  }
  async function stage() {
    if (!reviewed || !selected.length || selected.some((w) => !w.candidate && !w.preview))
      throw new Error('Validate selected weeks and review the comparisons first.')
    for (const week of selected) {
      if (week.candidate) continue
      const result = await opsRequest<{ dataset_id: string }>(`batches/${week.batch_id}/stage`, csrf, 'POST', {
        review_reason: reason, review_acknowledged: true,
      })
      update(week.start_date, { candidate: result.dataset_id })
    }
    setNotice('Selected weeks staged. No published data changed.')
  }
  async function reviewPublication() {
    if (!selected.length || selected.some((w) => !w.candidate))
      throw new Error('Stage every selected week first.')
    // Refresh comparisons and the concurrency token in one operator action.
    const health = await opsRequest<OpsHealth>('health', csrf)
    for (const week of selected) {
      const preview = await opsRequest<Preview>(`batches/${week.batch_id}/preview`, csrf, 'POST')
      if (preview.comparison.baseline_dataset_id !== (health.active?.dataset_id ?? null))
        throw new Error('Published data changed during review. Review publication again.')
      update(week.start_date, { preview })
    }
    setBaseline(health.active?.dataset_id ?? null)
    setReviewed(false)
    setConfirm(true)
  }
  async function remember(week: Week) {
    if (!profile || !week.draft || !reviewed || locked)
      throw new Error('Review coverage before saving a persistent baseline, before staging any week.')
    await opsRequest(`batches/${week.batch_id}/coverage-profile`, csrf, 'POST', {
      buildings: week.draft.buildings, analysis_hash: week.analysis?.analysis_hash,
      profile_version: profile.version, review_reason: reason, review_acknowledged: true,
    })
    await discover()
    setNotice('Persistent windows approved in a new private profile version. Capture entries are retained; review the refreshed weeks.')
  }
  return <section className="ops-card ops-builder" aria-label="Multiweek timetable importer">
    <h3>Drop multiple timetable exports</h3>
    <p>Daily and weekly files are grouped by source dates into Sunday–Saturday weeks. Review and stage any selection; publication is always explicit.</p>
    <label>Weekly export start year, if absent from HTML
      <input type="number" min={1} max={9998} value={year} disabled={busy || locked}
        placeholder="Use verified source evidence" onChange={(e) => { setYear(e.target.value); setDiscoveryDirty(true); invalidate() }} />
    </label>
    <p className="small">For a December–January week, use the year of its Sunday. No year or capture time is taken from filenames, upload time or the computer clock.</p>
    <div className="ops-dropzone" onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => { e.preventDefault(); const incoming = [...e.dataTransfer.files]; void run(() => accept(incoming)) }}>
      <label>Choose or drop authorized HTML exports
        <input type="file" accept=".html,text/html" multiple disabled={busy || locked}
          onChange={(e) => { const incoming = [...(e.target.files ?? [])]; void run(() => accept(incoming)); e.target.value = '' }} />
      </label>
      <p className="small">Up to 84 files, 10 MB each, 100 MB total. A new selection replaces this private upload queue.</p>
    </div>
    {notice && <p className="notice" role="status">{notice}</p>}
    {exceptions.length > 0 && <div role="status"><h4>Source exceptions</h4><ul>
      {exceptions.map((e, i) => <li key={i}>{label(e.file)}: {e.code.replaceAll('_', ' ')}
        {['source_year_required', 'source_year_conflict', 'ambiguous_source_year'].includes(e.code) && <label>Verified Sunday year for this file
          <input type="number" min={1} max={9998} disabled={busy || locked} value={years[e.file] ?? ''}
            onChange={(event) => { setYears({ ...years, [e.file]: event.target.value }); setDiscoveryDirty(true); invalidate() }} />
        </label>}
      </li>)}
    </ul><p>Unresolved files are excluded, never marked free. You may publish independently reviewed weeks while other files remain unresolved.</p></div>}
    {parent && <div className="ops-actions">
      <button className="button secondary" disabled={busy || locked} onClick={() => void run(() => discover())}>Resolve metadata & detect again</button>
      <button className="text-button" disabled={busy} onClick={() => void run(async () => {
        await opsRequest(`batches/${parent}`, csrf, 'DELETE')
        setParent(''); setFiles([]); setWeeks([]); setExceptions([]); setConfirm(false)
        setNotice('Private uploads discarded. Dataset history and published weeks are retained.')
      })}>Discard private uploads</button>
    </div>}
    {weeks.length > 0 && !profile && <p className="notice warning">An approved inventory is required. Use the existing inventory editor below to establish mappings and expected room counts, then detect again.</p>}
    {sources.length > 0 && <fieldset disabled={busy} className="ops-source-metadata"><legend>Capture evidence for each original export</legend>
      {sources.map((file) => <div key={file} className="ops-upload"><strong>{label(file)}</strong>
        <label>Actual capture timestamp, including Z or UTC offset
          <input value={captures[file] ?? ''} disabled={weeks.some((w) => w.candidate && w.files.some((f) => f.file === file))} placeholder="YYYY-MM-DDTHH:mm:ss-04:00"
            onChange={(e) => { setCaptures({ ...captures, [file]: e.target.value }); invalidate() }} />
        </label>
        <label>Evidence reference (capture log, source export metadata, or recorded retrieval)
          <input maxLength={500} value={evidence[file] ?? ''} disabled={weeks.some((w) => w.candidate && w.files.some((f) => f.file === file))}
            onChange={(e) => { setEvidence({ ...evidence, [file]: e.target.value }); invalidate() }} />
        </label>
      </div>)}
    </fieldset>}
    {weeks.map((week) => <div key={week.start_date} className="ops-card">
      <label className="ops-check"><input type="checkbox" checked={week.selected} disabled={busy || confirm}
        onChange={(e) => { update(week.start_date, { selected: e.target.checked }); setReviewed(false) }} />Week starting {week.start_date}</label>
      <p>{week.files.map((f) => `${label(f.file)} (${f.format}, ${f.period}, ${f.date_evidence})`).join(' · ')}</p>
      {week.blocking.map((b) => <p key={b} className="notice warning">Blocking: {b.replaceAll('_', ' ')}</p>)}
      {week.analysis && <>
        <p>{week.analysis.summary.rooms} rooms · {week.analysis.summary.occurrences} bookings · profile v{week.analysis.profile_version}</p>
        {week.analysis.missing_sources.length > 0 && <p className="notice warning">Missing dates: {week.analysis.missing_sources.join(', ')}</p>}
        <p>Inventory changes: {week.analysis.differences.added_rooms.length} unfamiliar, {week.analysis.differences.missing_rooms.length} missing, {week.analysis.differences.capacity_changes.length} capacities, {week.analysis.differences.source_id_changes.length} source identities. Resolve inventory exceptions in the existing editor.</p>
        {week.analysis.issues.map((issue, i) => <p key={i} className="notice warning">{issue.severity}: {issue.code.replaceAll('_', ' ')} {issue.room}</p>)}
        {week.analysis.differences.window_changes.length > 0 && <div className="ops-table" tabIndex={0} role="region" aria-label={`Coverage window review for ${week.start_date}`}><table>
          <caption>Proposed observed coverage windows — this week only</caption>
          <thead><tr><th>Room</th><th>Approved</th><th>Observed</th><th>Review</th></tr></thead>
          <tbody>{week.analysis.differences.window_changes.map((c, i) => <tr key={i}><th>{c.room}</th>
            <td>{c.expected.start}–{c.expected.end}</td><td>{c.observed.start}–{c.observed.end}</td>
            <td>{c.eligible ? 'Continuous grid; proposed' : 'Unresolved; blocked'}</td></tr>)}</tbody>
        </table></div>}
        <button className="text-button" disabled={busy || locked || !reviewed || !reason || !week.draft}
          onClick={() => void run(() => remember(week))}>Separately approve these windows for future imports</button>
      </>}
      {week.preview && <div><h4>Comparison with this period’s active dataset</h4>
        <p>Replacing {week.preview.comparison.replaced_dataset_id ?? 'no active data for these dates'} · {week.preview.comparison.added_intervals} added / {week.preview.comparison.removed_intervals} removed intervals.</p>
        {week.preview.comparison.warnings.map((w) => <p key={w} className="notice warning">{w.replaceAll('_', ' ')}</p>)}
        <details><summary>Inventory and source comparison</summary><pre>{JSON.stringify(week.preview.comparison, null, 2)}</pre></details>
      </div>}
      {week.candidate && <p>Staged dataset: <strong>{week.candidate}</strong></p>}
    </div>)}
    {weeks.length > 0 && <>
      <label>Review reason code<input maxLength={64} value={reason} disabled={busy || locked}
        placeholder="weekly-source-review" onChange={(e) => { setReason(e.target.value); invalidate() }} /></label>
      <label className="ops-check"><input type="checkbox" checked={reviewed} disabled={busy}
        onChange={(e) => setReviewed(e.target.checked)} />
        I reviewed selected dates and years, approved room mappings, all proposed coverage changes, original capture evidence, and displayed comparisons. Coverage outside the observed grids remains unknown.
      </label>
      <div className="ops-actions">
        <button className="button secondary" disabled={busy || discoveryDirty || !reviewed || !profile || !selected.length}
          onClick={() => void run(validateWeeks)}>Approve eligible windows & validate selected weeks</button>
        <button className="button secondary" disabled={busy || !reviewed || !selected.length || selected.some((w) => !w.candidate && !w.preview)}
          onClick={() => void run(stage)}>Stage reviewed weeks</button>
        <button className="button primary" disabled={busy || !selected.length || selected.some((w) => !w.candidate)}
          onClick={() => void run(reviewPublication)}>Review atomic publication</button>
      </div>
    </>}
    {confirm && <div className="notice warning" role="region" aria-label="Explicit publication confirmation">
      <h4>Publish this exact selection together?</h4>
      <p>Only these periods are added or replaced. All other active weeks and dataset history are retained.</p>
      <ul>{selected.map((w) => <li key={w.start_date}>{w.start_date}: {w.candidate}</li>)}</ul>
      <p>Publication baseline: {baseline ?? 'none'}. Public republication of intranet-derived data still requires verified authorization.</p>
      <button className="button primary" disabled={busy || !reviewed} onClick={() => void run(async () => {
        const result = await opsRequest<{ health: OpsHealth }>('publications', csrf, 'POST', {
          batch_ids: selected.map((w) => w.batch_id), confirm_dataset_ids: selected.map((w) => w.candidate),
          baseline_dataset_id: baseline, review_reason: reason, review_acknowledged: reviewed,
        })
        onHealth(result.health); setConfirm(false); setNotice('The selected publication transaction committed. Active periods are listed in Overview.')
      })}>Confirm publish selected datasets</button>
      <button className="text-button" disabled={busy} onClick={() => setConfirm(false)}>Cancel</button>
    </div>}
  </section>
}
