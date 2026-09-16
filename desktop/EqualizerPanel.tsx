import { useEffect, useRef, useState } from 'react'
import { projectEqualizer, type EqualizerChange, type EqualizerState } from './equalizer'
import { useModalFocusTrap } from './modalFocus'

export function EqualizerPanel({ onClose }: { onClose: () => void }) {
  const [state, setState] = useState<EqualizerState | null>(null)
  const [draft, setDraft] = useState<Record<string, number>>({})
  const [error, setError] = useState<string | null>(null)
  const [preset, setPreset] = useState('Flat')
  const [name, setName] = useState('')
  const [pending, setPending] = useState(false)
  const stateRef = useRef<EqualizerState | null>(null)
  const queue = useRef(new Map<string, EqualizerChange>())
  const busy = useRef(false)
  const mounted = useRef(true)
  const generation = useRef(0)
  const { dialogRef, containTabFocus } = useModalFocusTrap(true, { onOutsidePointer: onClose })

  useEffect(() => {
    mounted.current = true
    const accept = (value: unknown) => {
      const next = projectEqualizer(value)
      if (!next || (stateRef.current && next.revision < stateRef.current.revision)) return
      stateRef.current = next
      setState(next)
    }
    const unsubscribe = window.mariana.backend.onEvent((event) => {
      if (event.event === 'equalizer') accept(event.payload)
      if (event.event === 'starting') {
        generation.current += 1
        queue.current.clear()
        stateRef.current = null
        setState(null)
        setDraft({})
        setError(null)
      }
    })
    let polling = false
    const poll = async () => {
      if (polling || busy.current) return
      polling = true
      const epoch = generation.current
      try {
        const result = await window.mariana.backend.equalizerStatus()
        if (mounted.current && epoch === generation.current) {
          if (result.ok) accept(result.state)
          else setError(result.error)
        }
      } catch { if (mounted.current) setError('Equalizer backend is unavailable') }
      finally { polling = false }
    }
    void poll()
    const timer = setInterval(() => void poll(), 500)
    return () => { mounted.current = false; clearInterval(timer); unsubscribe() }
  }, [])

  // A bounded latest-value map coalesces slider bursts. One request is in flight;
  // acknowledgements supply the revision for the next intent, including the final value.
  const submit = async (key: string, change: EqualizerChange) => {
    queue.current.set(key, change)
    if (busy.current || !stateRef.current) return
    busy.current = true
    setPending(true)
    setError(null)
    const epoch = generation.current
    try {
      while (queue.current.size && stateRef.current) {
        const [nextKey, nextChange] = queue.current.entries().next().value!
        queue.current.delete(nextKey)
        const result = await window.mariana.backend.equalizerConfigure({ ...nextChange, revision: stateRef.current.revision })
        if (epoch !== generation.current) break
        if (!result.ok) {
          queue.current.clear()
          if (mounted.current) setError(result.error)
          break
        }
        const next = projectEqualizer(result.state)
        if (!next) throw new Error('Invalid equalizer response')
        stateRef.current = next
        if (mounted.current) setState(next)
      }
    } catch { queue.current.clear(); if (mounted.current) setError('Could not update equalizer') }
    finally {
      busy.current = false
      if (mounted.current) { setPending(false); setDraft({}) }
    }
  }

  const close = () => onClose()
  const frequencies = state?.response.map(([hz]) => hz) || []
  const minimum = frequencies[0] || 20
  const maximum = frequencies.at(-1) || 20000
  const curve = state?.response.map(([hz, db]) => `${40 + 550 * Math.log(hz / minimum) / Math.log(maximum / minimum)},${60 - Math.max(-36, Math.min(36, db)) * 1.5}`).join(' ')
  return (
    <div className="equalizer-backdrop">
    <section ref={dialogRef} className="equalizer-dialog" role="dialog" aria-modal="true" aria-label="Equalizer" tabIndex={-1}
      onKeyDown={(event) => { event.stopPropagation(); containTabFocus(event); if (event.key === 'Escape') { event.preventDefault(); close() } }}>
      <div className="popover-heading"><strong>Equalizer · local listening</strong><button type="button" aria-label="Close equalizer" onClick={close}>×</button></div>
      {!state ? <p role="status">Connecting to the equalizer…</p> : <>
        <label><input type="checkbox" checked={state.enabled} disabled={pending} onChange={(event) => void submit('enabled', { operation: 'enabled', enabled: event.target.checked })} /> Enable EQ (unchecked = bypass)</label>
        <svg className="eq-response" viewBox="0 0 600 120" role="img" aria-label="Implemented EQ frequency response including preamp, minus 36 to plus 36 dB">
          <path d="M40 24H590M40 60H590M40 96H590" className="eq-zero" /><polyline points={curve} fill="none" />
          <text x="0" y="28">+24</text><text x="0" y="64">0 dB</text><text x="0" y="100">−24</text>
          <text x="40" y="116">20 Hz</text><text x="510" y="116">{Math.round(maximum / 1000)} kHz</text>
        </svg>
        <div className="eq-bands">
          {state.frequencies.map((hz, index) => <label className="eq-band" key={hz}>
            <span>{hz >= 1000 ? `${hz / 1000}k` : hz} Hz</span>
            <input type="range" min={-12} max={12} step={0.5} aria-label={`${hz} Hz gain`} aria-orientation="vertical"
              disabled={!state.available_bands[index] || state.fault} value={draft[String(hz)] ?? state.bands[index]}
              onChange={(event) => { const value = Number(event.target.value); setDraft((old) => ({ ...old, [hz]: value })); void submit(String(hz), { operation: 'band', frequency: hz, gain: value }) }} />
            <output>{(draft[String(hz)] ?? state.bands[index]).toFixed(1)} dB</output>
            {!state.available_bands[index] && <small>Unavailable at this rate</small>}
          </label>)}
        </div>
        <label className="eq-preamp">Preamp · {(draft.preamp ?? state.preamp).toFixed(1)} dB
          <input type="range" aria-label="EQ preamp" min={-36} max={12} step={0.5} value={draft.preamp ?? state.preamp} disabled={state.fault}
            onChange={(event) => { const value = Number(event.target.value); setDraft((old) => ({ ...old, preamp: value })); void submit('preamp', { operation: 'preamp', gain: value }) }} />
        </label>
        <p className="eq-note">Suggested preamp: {state.recommended_preamp} dB. Not applied automatically; no limiter. Broadcasts are unchanged.</p>
        <p role="status">{state.overload_blocks ? `Overload detected in ${state.overload_blocks} blocks; reduce preamp.` : 'No EQ overload detected since playback reset.'} {state.fault ? 'EQ unavailable; playback is bypassed.' : `${state.sample_rate} Hz processing`}</p>
        {state.warning && <p role="alert">{state.warning}</p>}
        <div className="eq-presets">
          <label>Preset <select aria-label="Equalizer preset" value={preset} onChange={(event) => setPreset(event.target.value)}>
            {state.presets.map((item) => <option key={item.name} value={item.name}>{item.name} ({item.factory ? 'factory' : 'user'})</option>)}
          </select></label>
          <button disabled={pending} onClick={() => void submit('preset', { operation: 'preset-apply', name: preset })}>Apply</button>
          <button disabled={pending || !state.presets.some((item) => item.name === preset && !item.factory)} onClick={() => void submit('preset', { operation: 'preset-delete', name: preset })}>Delete user preset</button>
          <label>New preset <input aria-label="New preset name" maxLength={48} value={name} onChange={(event) => setName(event.target.value)} /></label>
          <button disabled={pending || !name.trim()} onClick={() => void submit('preset', { operation: 'preset-save', name })}>Save new</button>
          <button disabled={pending} onClick={() => void submit('reset', { operation: 'reset' })}>Reset to flat</button>
        </div>
        <small>Reset and presets preserve enabled/bypassed state. Tonal preferences, not stem isolation.</small>
      </>}
      {error && <p role="alert">{error}</p>}
    </section>
    </div>
  )
}
