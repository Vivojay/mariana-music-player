import { useRef, useState, type CSSProperties } from 'react'
import { createRoot } from 'react-dom/client'
import { HomepagePanel } from '../../HomepagePanel'
import { KeyboardShortcuts } from '../../KeyboardShortcuts'
import { TerminalSurface } from '../../TerminalSurface'
import { CaptionSelection } from '../../CaptionSelection'
import { themes } from '../../themes'
import type { HomepageProjection } from '../../shared'
import '../../styles.css'
import '../../localVideo.css'

// Real renderer components and browser focus, with isolated in-memory IPC.
// This fixture does not claim native backend, decoder, or device acceptance.
document.body.dataset.terminalWrites = '0'
document.body.dataset.playbackActions = '0'
const record = (operation: string, args: unknown[]) => {
  document.body.dataset.intent = JSON.stringify({ operation, args })
  if (operation === 'pause') document.body.dataset.playbackActions = String(Number(document.body.dataset.playbackActions) + 1)
  return Promise.resolve({ ok: true as const })
}
Object.defineProperty(window, 'mariana', { value: {
  terminal: {
    history: async () => '', resize: () => {}, onData: () => () => {},
    write: () => { document.body.dataset.terminalWrites = String(Number(document.body.dataset.terminalWrites) + 1) },
  },
  clipboard: { writeText: async () => {} }, openExternal: async () => {},
  backend: {
    pause: (...args: unknown[]) => record('pause', args),
    videoCaptionSelect: (...args: unknown[]) => record('select', args),
    videoCaptionLanguages: (...args: unknown[]) => record('languages', args),
    videoCaptionAutomatic: (...args: unknown[]) => record('automatic', args),
  },
} })
const home: HomepageProjection = {
  schema_version: 2, show_on_startup: true, online_enabled: false, state: 'offline',
  refreshed_at: null, safe_message: 'Online discovery is off.', sections: [{
    key: 'library', title: 'Your music', items: [{ id: 'library', title: 'Local music',
      source: 'Mariana library', summary: 'No network required.', published_at: null,
      link: null, image_key: null, image_mime: null }],
  }],
}
export function Fixture() {
  const [homeOpen, setHomeOpen] = useState(true)
  const [guideOpen, setGuideOpen] = useState(false)
  const [captionsOpen, setCaptionsOpen] = useState(false)
  const homeTrigger = useRef<HTMLButtonElement>(null)
  const chrome = themes.aurora.chrome
  const style = { '--app-bg': chrome.background, '--panel': chrome.panel, '--border': chrome.border,
    '--accent': chrome.accent, '--text': chrome.text, '--muted': chrome.muted, '--glow': chrome.glow,
  } as CSSProperties
  return <main className="app" style={style}>
    <header className="titlebar"><div className="titlebar-main">
      <button ref={homeTrigger} onClick={() => setHomeOpen(true)}>Home</button>
      <KeyboardShortcuts actions={{ toggle: () => { void window.mariana.backend.pause('fixture-media') }, home: () => setHomeOpen(true) }}
        onVisibilityChange={(open) => { setGuideOpen(open); if (open) setHomeOpen(false) }} />
      <button onClick={() => setCaptionsOpen(!captionsOpen)}>Video controls</button>
    </div></header>
    <div />
    <section style={{ position: 'relative', minHeight: 0 }}>
      <TerminalSurface theme={themes.aurora} fontSize={14} reducedMotion interactive={!homeOpen && !guideOpen && !captionsOpen} />
    </section>
    {homeOpen && <HomepagePanel homepage={home} onClose={() => {
      setHomeOpen(false); queueMicrotask(() => homeTrigger.current?.focus())
    }} onRefresh={() => {}} onOpenSettings={() => {}} onOpenLink={() => {}}
      loadImage={async () => ({ ok: false, error: 'Offline' })} />}
    {captionsOpen && <section className="local-video-panel controls-visible">
      <div className="local-video-stage">
        <header className="local-video-controls local-video-top">
          <details className="local-video-sync"><summary>Captions &amp; sync</summary>
            <div className="local-video-sync-menu">
              <CaptionSelection mediaId="fixture-media" pending={false} local apply={async (request) => { await request() }}
                captions={{ available: true, enabled: true, label: 'English', source: 'sidecar', auto_status: 'loaded',
                  text: null, offset_ms: 0, revision: 7, selected_id: 'a'.repeat(32), preferred_languages: ['en'],
                  tracks: [{ id: 'a'.repeat(32), label: 'English', language: 'en', source: 'sidecar', codec: 'srt', default: true, forced: false }],
                }} />
            </div>
          </details>
          <button onClick={() => setCaptionsOpen(false)}>Audio only</button>
        </header>
      </div>
    </section>}
  </main>
}
createRoot(document.getElementById('root')!).render(<Fixture />)
