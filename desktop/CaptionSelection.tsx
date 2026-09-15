import { useState } from 'react'
import type { LocalVideoStatus } from './localVideo'
import type { DesktopControlResult } from './shared'

type Props = {
  captions: LocalVideoStatus['captions']
  mediaId: string
  pending: boolean
  local: boolean
  apply: (request: () => Promise<DesktopControlResult>) => Promise<void>
}

export function CaptionSelection({ captions, mediaId, pending, local, apply }: Props) {
  const api = window.mariana.backend
  const savedLanguages = (captions.preferred_languages ?? []).join(' ')
  const [draft, setDraft] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const provider = captions.tracks?.some((track) => track.source === 'provider' || track.source === 'provider-generated')
  if (!api.videoCaptionSelect || !api.videoCaptionLanguages || !api.videoCaptionAutomatic || (!local && !provider)) return null
  const languages = draft ?? savedLanguages
  const loading = captions.auto_status === 'loading'
  return <div className="caption-selection">
    <label>{local ? 'Caption track' : 'Caption track (select to fetch)'}
      <select aria-label="Caption track" disabled={pending || !(captions.tracks?.length)}
        value={captions.selected_id ?? ''} onChange={(event) => {
          const trackId = event.target.value
          if (trackId) void apply(() => api.videoCaptionSelect!(mediaId, captions.revision ?? 0, trackId))
        }}>
        <option value="" disabled>{loading ? 'Loading captions…' : 'No track selected'}</option>
        {captions.tracks?.map((track) => <option key={track.id} value={track.id}>
          {track.label} · {track.source} · {track.codec}{track.default ? ' · default' : ''}{track.forced ? ' · forced' : ''}
        </option>)}
      </select>
    </label>
    {local && <><button type="button" disabled={pending || loading} onClick={() => void apply(() => api.videoCaptionAutomatic!(mediaId))}>
      Automatic captions
    </button>
    <label>Preferred languages (first preferred)
      <input aria-label="Preferred caption languages" placeholder="en hi · blank for automatic" maxLength={69}
        value={languages} onChange={(event) => { setDraft(event.target.value); setError(null) }} />
    </label>
    <button type="button" disabled={pending} onClick={() => {
      const values = languages.trim() ? languages.trim().split(/\s+/) : []
      if (values.length > 5 || values.some((value) => !/^[a-z]{2,3}(?:-[a-z0-9]{2,8})?$/i.test(value))) {
        setError('Use up to five language codes, such as en hi or pt-BR.'); return
      }
      void apply(() => api.videoCaptionLanguages!(mediaId, values))
    }}>Save languages</button>
    <small>Local tracks only. Choices and timing are remembered. Automatic forgets this media’s saved choice.</small></>}
    {!local && <small>Selection downloads provider captions for this session only. Generated tracks are labelled; no automatic caption requests.</small>}
    {loading && <span role="status">Loading selected captions; playback continues.</span>}
    {(error || captions.message) && <span role="status">{error || captions.message}</span>}
  </div>
}
