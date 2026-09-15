import { timelineChapters, validateSeekIntent } from './playbackSeek'
import { SeekTimeline } from './SeekTimeline'
import { hotspotAreaPoints } from './playbackHotspots'
import type { PlaybackHotspots, PlaybackStatus } from './shared'
import type { VideoBufferCoverage } from './videoBuffering'

type Props = {
  status: PlaybackStatus
  displayTitle?: string
  seekEnabled?: boolean
  seekPending?: boolean
  snapChapters?: boolean
  onSeek?: (seconds: number, mediaId: string) => void
  overlayContainer?: HTMLElement | null
  hotspots?: PlaybackHotspots | null
  expandedHitTarget?: boolean
  videoBuffered?: VideoBufferCoverage | null
}

function finiteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function safePreferredRegion(
  status: PlaybackStatus,
  duration: number | null,
): { startPercent: number; endPercent: number } | null {
  if (!status.finite || status.live || !status.region.active || duration === null || duration <= 0) return null
  const projectedStart = status.region.start_seconds === null ? 0 : finiteNumber(status.region.start_seconds)
  const projectedEnd = status.region.end_seconds === null ? duration : finiteNumber(status.region.end_seconds)
  if (projectedStart === null || projectedEnd === null) return null
  const start = Math.min(duration, Math.max(0, projectedStart))
  const end = Math.min(duration, Math.max(0, projectedEnd))
  if (end <= start) return null
  return {
    startPercent: (start / duration) * 100,
    endPercent: (end / duration) * 100,
  }
}


export function PlaybackTimeline({
  status, displayTitle = status.title || 'Media', seekEnabled = false, seekPending = false,
  snapChapters = false, onSeek, overlayContainer, hotspots = null, expandedHitTarget = false, videoBuffered,
}: Props) {
  const duration = finiteNumber(status.duration_seconds)
  const percent = finiteNumber(status.percent)
  const progress = status.finite && !status.live && duration !== null && duration > 0 && percent !== null
    ? Math.min(100, Math.max(0, percent)) : null
  const chapterMarkers = progress === null ? [] : timelineChapters(status)
  const currentChapterMarker = chapterMarkers.find((marker) => marker.current)
  const preferredRegion = progress === null ? null : safePreferredRegion(status, duration)
  const bufferedSeconds = finiteNumber(status.buffered_seconds)
  const bufferedEndPercent = progress !== null && duration !== null && duration > 0 && bufferedSeconds !== null
    ? Math.min(100, Math.max(progress, ((status.position_seconds + Math.max(0, bufferedSeconds)) / duration) * 100))
    : null
  const hotspotPoints = duration !== null && hotspots?.media_id === status.media_id
    ? hotspotAreaPoints(hotspots, duration) : ''
  const videoRanges = progress !== null && duration !== null && videoBuffered?.mediaId === status.media_id
    ? videoBuffered.ranges.filter(({ start, end }) => Number.isFinite(start) && Number.isFinite(end)
      && start >= 0 && end > start && end <= duration).slice(0, 64) : []
  const seekInteractive = Boolean(progress !== null && onSeek
    && validateSeekIntent(status, status.media_id, status.position_seconds, seekEnabled).ok)
  // A confirmed in-flight seek temporarily publishes Seeking. Retain only its
  // existing draft panel; the controls remain disabled until authoritative readiness.
  const retainPendingPreview = seekPending && status.state === 'seeking'
    && validateSeekIntent({ ...status, state: 'paused' }, status.media_id, status.position_seconds, true).ok
  const timelineIdentity = JSON.stringify([status.media_id, duration, status.region, seekInteractive || retainPendingPreview,
    chapterMarkers.map((marker) => [marker.title, marker.start_time, marker.end_time])])
  const progressContents = (
    <>
      {hotspotPoints && (
        <svg className="playback-hotspots" viewBox="0 0 1000 30" preserveAspectRatio="none"
          role="img" aria-label="Personal interaction hotspots">
          <title>Personal interaction hotspots based on this installation&apos;s play, pause, and seek actions</title>
          <polygon points={hotspotPoints} />
        </svg>
      )}
      <progress
        className="playback-progress"
        aria-label={`Playback progress for ${displayTitle}`}
        aria-valuetext={`${Math.round(progress ?? 0)}%`}
        max="100"
        value={progress ?? 0}
      />
      {bufferedEndPercent !== null && bufferedEndPercent > (progress ?? 0) && (
        <span className={`playback-buffered-region${videoBuffered !== undefined ? ' has-video-buffer' : ''}`}
          data-buffer-kind="audio" aria-hidden="true" style={{
          left: `${progress ?? 0}%`,
          width: `${bufferedEndPercent - (progress ?? 0)}%`,
        }} />
      )}
      {videoRanges.map(({ start, end }) => <span key={`${start}-${end}`}
        className="playback-video-buffered-region" data-buffer-kind="video" aria-hidden="true"
        data-start-seconds={start} data-end-seconds={end}
        style={{ left: `${start / duration! * 100}%`, width: `${(end - start) / duration! * 100}%` }} />)}
      <span className="playback-position-dot" aria-hidden="true" style={{ left: `${progress ?? 0}%` }} />
      {preferredRegion && (
        <span
          className="playback-preferred-region"
          data-start-percent={preferredRegion.startPercent}
          data-end-percent={preferredRegion.endPercent}
          aria-hidden="true"
          style={{
            left: `${preferredRegion.startPercent}%`,
            width: `${preferredRegion.endPercent - preferredRegion.startPercent}%`,
          }}
        />
      )}
      {chapterMarkers.length > 0 && (
        <span className="playback-chapter-markers" aria-hidden="true">
          {currentChapterMarker && (
            <span
              className="playback-chapter-current"
              data-chapter-index={currentChapterMarker.index}
              style={{
                left: `${currentChapterMarker.start_percent}%`,
                width: `${currentChapterMarker.end_percent - currentChapterMarker.start_percent}%`,
              }}
            />
          )}
          {chapterMarkers.filter((marker) => marker.start_percent > 0).map((marker) => (
            <span
              key={`${marker.index}-${marker.start_percent}`}
              className="playback-chapter-boundary"
              data-chapter-index={marker.index}
              style={{ left: `${marker.start_percent}%` }}
            />
          ))}
        </span>
      )}
    </>
  )

  return <>{progress !== null ? (
    onSeek ? (
      <SeekTimeline
        key={timelineIdentity}
        status={status}
        enabled={seekInteractive}
        pending={seekPending}
        snapChapters={snapChapters}
        onSeek={onSeek}
        overlayContainer={overlayContainer}
        expandedHitTarget={expandedHitTarget}
      >
        {progressContents}
      </SeekTimeline>
    ) : (
      <span className={`playback-progress-track ${expandedHitTarget ? 'has-expanded-hit-target' : ''}`}>{progressContents}</span>
    )
  ) : (
    <span className={`playback-progress-placeholder ${status.live ? 'is-live' : 'is-unknown'}`} aria-hidden="true" />
  )}</>
}
