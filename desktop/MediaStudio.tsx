import { useEffect, useMemo, useRef, useState } from 'react'
import type { PlaybackStatus } from './shared'
import { clipFormats, segmentAt, type ClipFormat, type Stage, type StudioAction, type StudioResult } from './mediaStudioProtocol'
import { useModalFocusTrap } from './modalFocus'
import './mediaStudio.css'

type Mode = 'karaoke' | 'clip'
type Props = { status: PlaybackStatus | null; ready: boolean }
const invoke = async (intent: StudioAction): Promise<StudioResult> => {
  try {
    return await window.mariana.backend.mediaStudio?.(intent) ?? { ok: false, error: 'Restart the desktop player to enable this feature.' }
  } catch { return { ok: false, error: 'The player connection was interrupted.' } }
}
const fraction = (seconds: number) => Number(seconds.toFixed(3))
const clock = (ms: number) => `${Math.floor(ms / 60000)}:${Math.floor(ms / 1000 % 60).toString().padStart(2, '0')}`

// Extrapolate only while native audio is playing. A late or lost snapshot freezes
// the display after one normal update interval; seeks/pauses reset the source clock.
function useKaraokeClock(status: PlaybackStatus) {
  const anchor = status.position_seconds * 1000
  const playing = status.state === 'playing'
  const [frame, setFrame] = useState({ anchor, position: anchor })
  useEffect(() => {
    if (!playing) return
    const started = performance.now()
    setFrame({ anchor, position: anchor })
    const timer = setInterval(() => {
      const predicted = anchor + Math.min(performance.now() - started, 1100)
      setFrame({ anchor, position: Math.min(predicted, (status.duration_seconds ?? Infinity) * 1000) })
    }, 45)
    return () => clearInterval(timer)
  }, [anchor, playing, status.duration_seconds])
  return playing && frame.anchor === anchor ? frame.position : anchor
}

function KaraokeStage({ status }: { status: PlaybackStatus & { media_id: string } }) {
  const mediaId = status.media_id
  const [stage, setStage] = useState<Stage | null>(null)
  const [message, setMessage] = useState('')
  const [part, setPart] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  const alive = useRef(false)
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])
  useEffect(() => {
    let active = true
    setBusy(true)
    void invoke({ action: 'karaoke.stage', mediaId }).then((result) => {
      if (!active) return
      setBusy(false)
      if (result.stage?.mediaId === mediaId) { setStage(result.stage); setMessage('') }
      else { setStage(null); setMessage(result.error || 'Playback changed. Refresh karaoke timing.') }
    })
    return () => { active = false }
  }, [mediaId, revision])
  const update = async (intent: StudioAction) => {
    setBusy(true); setMessage('')
    const result = await invoke(intent)
    if (!alive.current) return
    setBusy(false)
    if (!result.ok) setMessage(result.error || 'Could not update karaoke.')
    else if (result.stage?.mediaId === mediaId) { setPart(''); setStage(result.stage) }
    else if (intent.action === 'karaoke.vocals') setMessage(intent.mode === 'off' ? 'Backing track selected.' : 'Original vocals selected.')
  }
  const singers = useMemo(() => Array.from(new Set(stage?.segments.flatMap(s => s.voices.map(v => v.singer)) ?? [])), [stage])
  const position = useKaraokeClock(status)
  const index = stage ? segmentAt(stage.segments, position) : -1
  const active = stage?.segments[index]
  const next = useMemo(() => stage && index >= 0
    ? stage.segments.slice(index + 1).find(segment => segment.voices.some(v => !part || v.singer === part)) : null, [stage, index, part])
  return <>
    <div className="studio-actions">
      <button type="button" disabled={busy} onClick={() => void update({ action: 'karaoke.import', mediaId })}>Import timing…</button>
      <button type="button" disabled={busy} onClick={() => setRevision(value => value + 1)}>Refresh</button>
      {singers.length > 1 && <label>Practice part <select value={part} onChange={e => setPart(e.target.value)}>
        <option value="">All singers</option>{singers.map(name => <option key={name}>{name}</option>)}</select></label>}
    </div>
    {stage?.segments.length ? <>
      <div className="studio-score"><span>{clock(position)}</span><span>{Math.floor((stage.score ?? 0) * 100)}% timing confidence · {stage.source}</span></div>
      <div className="studio-voices" aria-label="Synchronized singer parts">
        {active?.voices.length ? active.voices.map(v => <section key={v.singer} className={part && part !== v.singer ? 'studio-part dim' : 'studio-part'}>
          <h3>{v.singer}</h3><p>{v.words.map(w => <span key={w.start_ms} className={position >= w.end_ms ? 'sung' : position >= w.start_ms ? 'singing' : ''}
            aria-current={position >= w.start_ms && position < w.end_ms ? 'true' : undefined}>{w.text}{' '}</span>)}</p>
        </section>) : <p className="studio-rest">{position >= stage.segments[stage.segments.length - 1].end_ms ? 'End of lyrics' : 'Instrumental'}</p>}
      </div>
      {next && <div className="studio-next"><strong>Up next · {clock(next.start_ms)}</strong>
        {next.voices.filter(v => !part || v.singer === part).map(v => <p key={v.singer}>{v.singer} · {v.words.map(w => w.text).join(' ')}</p>)}</div>}
      <div className="studio-actions">
        <button disabled={busy} onClick={() => void update({ action: 'karaoke.vocals', mediaId, mode: 'off' })}>Use backing stems</button>
        <button disabled={busy} onClick={() => void update({ action: 'karaoke.vocals', mediaId, mode: 'on' })}>Use original vocals</button>
      </div>
    </> : <div className="studio-empty"><strong>{busy ? 'Checking timing…' : 'Karaoke unavailable'}</strong>
      <p>{stage?.reason || (!busy && 'Karaoke needs word timing for this exact recording, with at least 90% confidence throughout.')}</p>
      {stage?.score != null && <p>Whole-recording score · {Math.floor(stage.score * 100)}%</p>}</div>}
    {message && <p role="status">{message}</p>}
  </>
}

function ClipEditor({ status }: { status: PlaybackStatus & { media_id: string } }) {
  const mediaId = status.media_id
  const duration = status.duration_seconds ?? 0
  const [start, setStart] = useState(String(fraction(Math.max(0, Math.min(status.position_seconds, duration - 15)))))
  const [end, setEnd] = useState(String(fraction(Math.min(duration, Number(start) + 15))))
  const [format, setFormat] = useState<ClipFormat>('m4a')
  const [message, setMessage] = useState('Checking this recording…')
  const [canLink, setCanLink] = useState(false)
  const [available, setAvailable] = useState(false)
  const [busy, setBusy] = useState(false)
  const [job, setJob] = useState('')
  const alive = useRef(false)
  useEffect(() => {
    let active = true
    alive.current = true
    void invoke({ action: 'clip.status', mediaId }).then(result => {
      if (!active) return
      const clip = result.clip?.mediaId === mediaId ? result.clip : null
      setAvailable(Boolean(clip?.available))
      setCanLink(Boolean(clip?.canLink))
      setMessage(clip?.reason || result.error || (clip ? '' : 'Playback changed. Reopen the clip editor.'))
      if (clip?.start != null) setStart(String(clip.start))
      if (clip?.end != null) setEnd(String(clip.end))
    })
    return () => { active = false; alive.current = false }
  }, [mediaId])
  useEffect(() => {
    if (!job) return
    let active = true
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      const result = await invoke({ action: 'clip.job', jobId: job })
      if (!active) return
      setMessage(result.message || result.error || 'Preparing your clip…')
      if (result.phase === 'rendering') timer = setTimeout(() => void poll(), 400)
      else { setBusy(false); setJob('') }
    }
    void poll()
    return () => { active = false; clearTimeout(timer) }
  }, [job])
  const valid = start.trim() && end.trim() && Number(start) >= 0 && Number(end) > Number(start) && Number(end) <= duration
  async function create(action: 'clip.share' | 'clip.export') {
    if (!valid || !available || busy) return
    setBusy(true); setMessage('')
    const result = await invoke({ action, mediaId, start: Number(start), end: Number(end), format })
    if (!alive.current) return
    if (result.jobId) { setMessage('Preparing your clip…'); setJob(result.jobId) }
    else { setBusy(false); setMessage(result.error || '') }
  }
  return <>
    {canLink && <button onClick={async () => {
      const result = await invoke({ action: 'clip.link', mediaId })
      if (alive.current) setMessage(result.ok ? 'YouTube timestamp link copied.' : result.error || 'Could not copy link.')
    }}>Copy YouTube timestamp link</button>}
    <div className="studio-marks">
      <label>Start (seconds)<input type="number" min="0" max={duration} step=".001" disabled={!available || busy} value={start} onChange={e => setStart(e.target.value)} /></label>
      <button disabled={!available || busy} onClick={() => setStart(String(fraction(status.position_seconds)))}>Set start here</button>
      <label>End (seconds)<input type="number" min="0" max={duration} step=".001" disabled={!available || busy} value={end} onChange={e => setEnd(e.target.value)} /></label>
      <button disabled={!available || busy} onClick={() => setEnd(String(fraction(status.position_seconds)))}>Set end here</button>
    </div>
    <div className="studio-actions"><label>Format <select value={format} disabled={!available || busy} onChange={e => setFormat(clipFormats.find(f => f === e.target.value) ?? 'm4a')}>
      {clipFormats.map(f => <option key={f} value={f}>{f === 'story' ? 'Vertical story · MP4' : f.toUpperCase()}</option>)}
    </select></label></div>
    <p>{valid ? `${fraction(Number(end) - Number(start))} seconds selected` : 'Set the end after the start and within the recording.'}</p>
    <div className="studio-actions"><button className="studio-primary" disabled={!available || busy || !valid} onClick={() => void create('clip.share')}>Prepare &amp; share</button>
      <button disabled={!available || busy || !valid} onClick={() => void create('clip.export')}>Save clip…</button></div>
    {message && <p role="status">{message}</p>}
  </>
}

export function MediaStudio({ status, ready }: Props) {
  const [mode, setMode] = useState<Mode | null>(null)
  const opener = useRef<HTMLButtonElement | null>(null)
  const close = () => { setMode(null); opener.current?.focus() }
  const { dialogRef, containTabFocus } = useModalFocusTrap(mode !== null, { onOutsidePointer: close })
  const guardedStatus = ready && status?.media_id ? { ...status, media_id: status.media_id } : null
  return <>
    {(['karaoke', 'clip'] as const).map(v => <button key={v} type="button" aria-haspopup="dialog"
      onClick={e => { opener.current = e.currentTarget; setMode(v) }}>{v === 'karaoke' ? 'Karaoke' : 'Share clip'}</button>)}
    {mode && <div className="studio-backdrop"><section ref={dialogRef} className="studio-dialog" role="dialog" aria-modal="true"
      aria-labelledby="studio-heading" tabIndex={-1} onKeyDown={e => {
        e.stopPropagation(); containTabFocus(e); if (e.key === 'Escape') { e.preventDefault(); close() }
      }}>
      <header><div><h2 id="studio-heading">{mode === 'karaoke' ? 'Karaoke' : 'Share a clip'}</h2>
        {guardedStatus && <p>{[status?.artist, status?.title].filter(Boolean).join(' · ')}</p>}</div>
        <button onClick={close} aria-label="Close panel">×</button></header>
      {guardedStatus ? mode === 'karaoke' ? <KaraokeStage key={guardedStatus.media_id} status={guardedStatus} />
        : <ClipEditor key={guardedStatus.media_id} status={guardedStatus} />
        : <p role="status">{ready ? 'Load a recording to use this feature.' : 'Waiting for the player…'}</p>}
    </section></div>}
  </>
}
