import { useEffect, useRef, type RefObject } from 'react'
import { freshVideoClock, videoClockTarget, type LocalVideoStatus } from './localVideo'

export type VideoClockSample = { status: LocalVideoStatus; timestamp: number }

const POLL_MS = 50
const SEEK_COOLDOWN_MS = 1200
const SEEK_THRESHOLD_SECONDS = 0.85
const CLOCK_JUMP_SECONDS = 0.40
const START_FAILURE = 'Video could not start; audio remains available'

type PendingPlay = {
  element: HTMLVideoElement
  sample: VideoClockSample
}

function followsClock(previous: VideoClockSample, next: VideoClockSample): boolean {
  if (previous === next) return true
  const { timestamp } = next
  if (!freshVideoClock(previous.timestamp, timestamp) || previous.status.playing !== next.status.playing
    || previous.status.audio_offset_ms !== next.status.audio_offset_ms) return false
  const expected = videoClockTarget(previous.status, previous.timestamp, timestamp)
  const actual = videoClockTarget(next.status, timestamp, timestamp)
  return Math.abs(expected.seconds - actual.seconds) < (next.status.playing ? CLOCK_JUMP_SECONDS : 0.05)
}

/** Silent presentation only: the backend clock remains the sole playback authority. */
export function useVideoFollower(
  video: RefObject<HTMLVideoElement | null>,
  clock: RefObject<VideoClockSample | null>,
  mediaId: string | null | undefined,
  handle: string | null | undefined,
  enabled: boolean,
  onError: (message: string) => void,
) {
  // Prevent duplicate play() attempts on the same element across effect runs.
  const pendingRef = useRef<PendingPlay | null>(null)
  useEffect(() => {
    if (!enabled || !handle) return
    let stopped = false
    let active: HTMLVideoElement | null = null
    let previous: VideoClockSample | null = null
    let align = true
    let lastSeek = -Infinity
    let failed = false

    const matches = (sample: VideoClockSample | null): sample is VideoClockSample => (
      sample !== null && sample.status.media_id === mediaId && sample.status.handle === handle && sample.status.state === 'ready'
    )
    const settle = (record: PendingPlay, reason: unknown) => {
      if (pendingRef.current !== record) return
      pendingRef.current = null
      if (reason === null || stopped) return
      // An interrupted play is expected when pausing; stay silent.
      if (reason instanceof DOMException && reason.name === 'AbortError') return
      const current = clock.current
      if (video.current !== record.element || !matches(current) || !freshVideoClock(current.timestamp, Date.now())
        || !followsClock(record.sample, current)) return
      failed = true
      onError(START_FAILURE)
    }
    const timer = window.setInterval(() => {
      const element = video.current
      const sample = clock.current
      if (stopped || !element) return
      if (element !== active) {
        active = element
        align = true
        lastSeek = -Infinity
        failed = false
      }
      const now = Date.now()
      if (!matches(sample) || !freshVideoClock(sample.timestamp, now)) {
        // Do not jump backward to an expired position when its extrapolation stops.
        if (previous || !element.paused) element.pause()
        previous = null
        align = true
        return
      }
      if (!previous || !followsClock(previous, sample)) align = true
      previous = sample
      const target = videoClockTarget(sample.status, sample.timestamp, now)
      const baseRate = sample.status.playback_rate ?? 1
      let drift = target.seconds - element.currentTime
      element.muted = true
      element.volume = 0

      if (element.readyState >= 1 && !element.seeking) {
        const recover = target.play && element.readyState >= 3 && Math.abs(drift) > SEEK_THRESHOLD_SECONDS
          && now - lastSeek >= SEEK_COOLDOWN_MS
        if (align || recover) {
          if (Math.abs(drift) > 0.05) {
            element.currentTime = Math.min(target.seconds, Number.isFinite(element.duration) ? element.duration : target.seconds)
            lastSeek = now
            drift = target.seconds - element.currentTime
          }
          align = false
        }
      }

      // Let the decoder finish a seek or refill before nudging an already playing picture.
      const adjust = !align && target.play && !element.paused && !element.seeking && element.readyState >= 3
        && Math.abs(drift) > 0.12
      const rate = adjust ? baseRate * (1 + Math.max(-0.05, Math.min(0.05, drift * 0.12))) : baseRate
      if (Math.abs(element.playbackRate - rate) > 0.005) element.playbackRate = rate
      if (!target.play) {
        if (!element.paused || pendingRef.current?.element === element) element.pause()
        return
      }
      if (element.paused && !failed && pendingRef.current?.element !== element) {
        // play() can begin buffering before metadata, but seek only once the timeline is known.
        const record: PendingPlay = { element, sample }
        pendingRef.current = record
        try {
          element.play().then(
            () => settle(record, null),
            (reason: unknown) => settle(record, reason),
          )
        } catch (error) {
          settle(record, error)
        }
      }
    }, POLL_MS)
    return () => {
      stopped = true
      window.clearInterval(timer)
      active?.pause()
    }
  }, [video, clock, mediaId, handle, enabled, onError])
}
