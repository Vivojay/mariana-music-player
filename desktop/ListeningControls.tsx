import { useEffect, useRef, useState } from 'react'
import { DEESSER_MODES, projectEqualizer, type DeesserMode, type EqualizerState } from './equalizer'
import { timelineChapters } from './playbackSeek'
import type { PlaybackStatus } from './shared'
import './listeningControls.css'

type Props = {
  ready: boolean
  status: PlaybackStatus | null
  seekEnabled: boolean
  onSeek: (seconds: number) => void
}

export function ListeningControls({ ready, status, seekEnabled, onSeek }: Props) {
  const [settings, setSettings] = useState<EqualizerState | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const generation = useRef(0)
  const busy = useRef(false)
  const accept = (value: unknown) => {
    const next = projectEqualizer(value)
    if (next) setSettings((current) => !current || next.revision >= current.revision ? next : current)
  }

  useEffect(() => {
    let active = true
    generation.current += 1
    busy.current = false
    const backend = window.mariana.backend
    if (!ready || !backend.equalizerStatus) return
    const unsubscribe = backend.onEvent((event) => {
      if (active && event.event === 'equalizer') accept(event.payload)
    })
    void backend.equalizerStatus().then((result) => {
      if (!active) return
      if (result.ok) accept(result.state)
      else setError('Voice settings are unavailable.')
    }).catch(() => { if (active) setError('Voice settings are unavailable.') })
    return () => { active = false; generation.current += 1; unsubscribe() }
  }, [ready, retry])

  const change = async (mode: DeesserMode) => {
    if (!settings || !ready || busy.current) return
    busy.current = true
    const epoch = generation.current
    setPending(true)
    setError('')
    try {
      const result = await window.mariana.backend.equalizerConfigure({ operation: 'deesser', revision: settings.revision, mode })
      if (epoch !== generation.current) return
      if (result.ok) accept(result.state)
      else setError('Could not save voice settings. Refresh to try again.')
    } catch {
      if (epoch === generation.current) setError('Voice settings are unavailable.')
    } finally {
      if (epoch === generation.current) { busy.current = false; setPending(false) }
    }
  }

  const chapterOptions = status?.source === 'podcast' ? timelineChapters(status) : []
  return <section className="listening-controls" aria-label="Podcast and audiobook settings">
    <strong>Podcasts &amp; audiobooks</strong>
    <label>
      Soften sharp S sounds
      <select aria-label="Soften sharp S sounds" value={settings?.deesser ?? ''}
        disabled={!settings || !ready || pending} onChange={(event) => {
          const mode = DEESSER_MODES.find((item) => item === event.target.value)
          if (mode) void change(mode)
        }}>
        {!settings && <option value="">Unavailable</option>}
        {DEESSER_MODES.map((mode) => <option key={mode} value={mode}>{mode[0].toUpperCase() + mode.slice(1)}</option>)}
      </select>
    </label>
    {status?.source === 'podcast' && <>
      <button type="button" disabled={!seekEnabled} onClick={() => onSeek(Math.max(0, status.position_seconds - 15))}>Back 15s</button>
      <button type="button" disabled={!seekEnabled} onClick={() => onSeek(status.position_seconds + 30)}>Forward 30s</button>
      {chapterOptions.length > 0 && <select aria-label="Jump to chapter" value="" disabled={!seekEnabled}
        onChange={(event) => { if (event.target.value) onSeek(Number(event.target.value)) }}>
        <option value="">Jump to chapter…</option>
        {chapterOptions.map((chapter) => <option key={chapter.start_time} value={chapter.start_time}>{chapter.title}</option>)}
      </select>}
    </>}
    {error && <><span role="status">{error}</span><button type="button" onClick={() => { setError(''); setRetry((v) => v + 1) }}>Refresh</button></>}
  </section>
}
