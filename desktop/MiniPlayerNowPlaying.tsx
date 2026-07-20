import { PlaybackStatusBar } from './PlaybackStatusBar'
import { formatChapterLabel, type PlaybackStatus } from './shared'

type MiniPlayerNowPlayingProps = {
  status: PlaybackStatus | null
  unavailableReason: string
}

function finiteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function formatTime(value: number): string {
  const total = Math.max(0, Math.floor(value))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${minutes}:${String(seconds).padStart(2, '0')}`
}

function preferredRegionLabel(status: PlaybackStatus | null): string {
  if (!status?.finite || status.live || !status.region.active) return ''
  const duration = finiteNumber(status.duration_seconds)
  if (duration === null || duration <= 0) return ''
  const projectedStart = status.region.start_seconds === null ? 0 : finiteNumber(status.region.start_seconds)
  const projectedEnd = status.region.end_seconds === null ? duration : finiteNumber(status.region.end_seconds)
  if (projectedStart === null || projectedEnd === null) return ''
  const start = Math.min(duration, Math.max(0, projectedStart))
  const end = Math.min(duration, Math.max(0, projectedEnd))
  if (end <= start) return ''
  return `Preferred region ${formatTime(start)}–${formatTime(end)}`
}

export function MiniPlayerNowPlaying({ status, unavailableReason }: MiniPlayerNowPlayingProps) {
  const chapterLabel = status?.finite && !status.live ? formatChapterLabel(status.chapter) : ''
  const regionLabel = preferredRegionLabel(status)
  return (
    <section className="mini-player-now-playing" aria-label="Now playing">
      <div
        className="mini-player-artwork-placeholder"
        role="img"
        aria-label="Album artwork unavailable"
        title="Album artwork unavailable"
      >
        <span aria-hidden="true">♪</span>
      </div>
      <PlaybackStatusBar status={status} unavailableReason={unavailableReason} />
      {(chapterLabel || regionLabel) && (
        <p className="mini-player-playback-context" aria-label="Playback context">
          {chapterLabel && <span>{chapterLabel}</span>}
          {regionLabel && <span>{regionLabel}</span>}
        </p>
      )}
    </section>
  )
}
