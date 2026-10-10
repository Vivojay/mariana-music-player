import { createRoot } from 'react-dom/client'
import { CaptionSelection } from '../../CaptionSelection'
import '../../styles.css'
import '../../localVideo.css'

// Renderer-only acceptance: native geometry and real controls, not a playback backend.
const record = (operation: string, args: unknown[]) => {
  document.body.dataset.captionIntent = JSON.stringify({ operation, args })
  return Promise.resolve({ ok: true })
}
Object.defineProperty(window, 'mariana', { value: { backend: {
  videoCaptionSelect: (...args: unknown[]) => record('select', args),
  videoCaptionLanguages: (...args: unknown[]) => record('languages', args),
  videoCaptionAutomatic: (...args: unknown[]) => record('automatic', args),
} } })

createRoot(document.getElementById('root')!).render(<main className="app">
  <section className="local-video-panel controls-visible" aria-label="Caption layout fixture">
    <div className="local-video-stage">
      <header className="local-video-controls local-video-top"><span>Video</span>
        <details className="local-video-sync" open><summary>Captions &amp; sync</summary>
          <div className="local-video-sync-menu">
            <CaptionSelection mediaId="fixture" pending={false} local apply={async (request) => { await request() }}
              captions={{ available: true, enabled: true, label: 'English', source: 'embedded', auto_status: 'loaded',
                text: null, offset_ms: 0, revision: 3, selected_id: 'a'.repeat(32), preferred_languages: ['eng'],
                tracks: [
                  { id: 'a'.repeat(32), label: 'English', language: 'eng', source: 'embedded', codec: 'subrip', default: true, forced: false },
                  { id: 'b'.repeat(32), label: 'Hindi', language: 'hin', source: 'sidecar', codec: 'srt', default: false, forced: false },
                ],
              }} />
          </div>
        </details>
        <button onClick={() => void document.querySelector('section')!.requestFullscreen()}>Fullscreen</button>
        <button>Audio only</button>
      </header>
    </div>
  </section>
</main>)
