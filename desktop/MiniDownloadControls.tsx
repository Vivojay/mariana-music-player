import { useRef, useState } from 'react'
import { activeDownload, formatTransfer, type DesktopDownloadJob } from './downloadProjection'
import type { PlaybackStatus } from './shared'

export function MiniDownloadControls({ playback, jobs, videoMode }: {
  playback: PlaybackStatus | null
  jobs: DesktopDownloadJob[]
  videoMode: boolean
}) {
  const pending = useRef(false)
  const [error, setError] = useState<string | null>(null)
  const [pendingFormat, setPendingFormat] = useState<'mp3' | 'mp4' | null>(null)
  const downloadable = Boolean(playback?.media_id && playback.finite && !playback.live
    && ['youtube', 'url', 'podcast'].includes(playback.source ?? '')
    && playback.policy.playable && !playback.policy.blocked)

  const start = async (format: 'mp3' | 'mp4') => {
    const mediaId = playback?.media_id
    if (!downloadable || !mediaId || pending.current) return
    pending.current = true
    setPendingFormat(format)
    setError(null)
    try {
      const result = await window.marianaMini.downloadCurrent(mediaId, format)
      if (!result.ok) setError(result.error || 'Download could not be started')
    } catch { setError('Download service is unavailable') }
    finally { pending.current = false; setPendingFormat(null) }
  }

  const formats: Array<'mp3' | 'mp4'> = videoMode ? ['mp4', 'mp3'] : ['mp3']
  return <div className="mini-downloads" aria-label="Current media downloads">
    {formats.map((format) => {
      const active = activeDownload(jobs, playback?.media_id, format)
      return <button key={format} type="button" disabled={!downloadable || Boolean(active) || pendingFormat !== null}
        title={!downloadable ? 'Only finite online media can be downloaded' : format === 'mp4' ? 'Save current video' : 'Extract current audio'}
        onClick={() => void start(format)}>
        {active ? `${format.toUpperCase()} ${formatTransfer(active)}` : pendingFormat === format ? 'Starting…'
          : format === 'mp4' ? 'Download video' : 'Download audio'}
      </button>
    })}
    {error && <span role="alert">{error}</span>}
  </div>
}
