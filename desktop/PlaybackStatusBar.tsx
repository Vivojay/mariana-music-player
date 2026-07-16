import type { PlaybackStatus } from './shared'

type PlaybackStatusBarProps = {
  status: PlaybackStatus | null
}

function finiteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function formatTime(value: unknown): string {
  const number = finiteNumber(value)
  const total = Math.max(0, Math.floor(number ?? 0))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${minutes}:${String(seconds).padStart(2, '0')}`
}

function sourceLabel(source: string | null | undefined): string | null {
  if (!source) return null
  const labels: Record<string, string> = {
    local: 'Local',
    youtube: 'YouTube',
    url: 'Online',
    podcast: 'Podcast',
    radio: 'Radio',
    recommendation: 'Recommendation',
  }
  if (labels[source]) return labels[source]
  return source.replaceAll('_', ' ').replace(/^./, (character) => character.toUpperCase())
}

function stateLabel(status: PlaybackStatus): string {
  return status.display_state?.trim()
    || status.state?.replaceAll('_', ' ').replace(/^./, (character) => character.toUpperCase())
    || 'Unknown'
}

export function PlaybackStatusBar({ status }: PlaybackStatusBarProps) {
  if (!status) {
    return (
      <section className="playback-status playback-status-empty" aria-label="Playback status">
        <span className="playback-title">Playback status unavailable</span>
        <span className="playback-state">Waiting for backend</span>
      </section>
    )
  }

  const state = stateLabel(status)
  const source = sourceLabel(status.source)
  const elapsed = formatTime(status.position_seconds)
  const duration = finiteNumber(status.duration_seconds)
  const rawPercent = finiteNumber(status.percent)
  const percent = rawPercent === null ? null : Math.min(100, Math.max(0, rawPercent))
  const progress = status.finite && !status.live && duration !== null && duration > 0
    ? percent
    : null
  const queuePosition = finiteNumber(status.queue_position)
  const queueCount = finiteNumber(status.queue_count)
  const hasQueuePosition = Boolean(
    queuePosition && queuePosition > 0 && queueCount && queueCount >= queuePosition,
  )
  const hasMedia = Boolean(status.media_id || status.title || status.artist)
  const title = status.title || (status.live ? 'Live stream' : hasMedia ? 'Media' : 'Nothing playing')
  const displayTitle = status.artist ? `${status.artist} — ${title}` : title
  const isFailed = status.state === 'failed'

  return (
    <section className={`playback-status playback-status-${status.state || 'unknown'}`} aria-label="Playback status">
      <span className="playback-identity" title={displayTitle}>
        <strong className="playback-title">{displayTitle}</strong>
        {source && <small className="playback-source">{source}</small>}
      </span>

      <span className="playback-state" data-state={status.state}>
        {status.live ? 'LIVE' : state}
      </span>

      <span className="playback-timing">
        {status.live ? (
          <span>{elapsed} elapsed</span>
        ) : duration !== null && duration > 0 ? (
          <span>{elapsed} / {formatTime(duration)}</span>
        ) : hasMedia ? (
          <span>{elapsed} / duration unknown</span>
        ) : (
          <span>No active media</span>
        )}
        {progress !== null && <span>{Math.round(progress)}%</span>}
      </span>

      <span className="playback-progress-slot">
        {progress !== null ? (
          <progress
            className="playback-progress"
            aria-label={`Playback progress for ${displayTitle}`}
            aria-valuetext={`${Math.round(progress)}%`}
            max="100"
            value={progress}
          />
        ) : (
          <span
            className={`playback-progress-placeholder ${status.live ? 'is-live' : 'is-unknown'}`}
            aria-hidden="true"
          />
        )}
      </span>

      {hasQueuePosition && (
        <span className="playback-queue" aria-label={`Queue item ${queuePosition} of ${queueCount}`}>
          Q {queuePosition}/{queueCount}
        </span>
      )}

      {isFailed && status.safe_error && (
        <span className="playback-error" title={status.safe_error}>{status.safe_error}</span>
      )}
    </section>
  )
}
