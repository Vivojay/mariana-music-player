import { useEffect, useRef, type RefObject } from 'react'
import { videoClockTarget, type LocalVideoStatus } from './localVideo'

export type VideoClockSample = { status: LocalVideoStatus; timestamp: number }

const POLL_MS = 50
const SEEK_DRIFT_SECONDS = 0.18
const START_FAILURE = 'Video could not start; audio remains available'

type PendingPlay = {
  element: HTMLVideoElement
  mediaId: string | null | undefined
  handle: string | null | undefined
  sample: VideoClockSample | null
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
  // One outstanding play attempt at most; shared across effect runs so a
  // replaced generation cannot issue a duplicate while its predecessor settles.
  const pendingRef = useRef<PendingPlay | null>(null)
  useEffect(() => {
    if (!enabled || !handle) return
    let stopped = false
    let active: HTMLVideoElement | null = null
    const settle = (record: PendingPlay, reason: unknown) => {
      if (pendingRef.current !== record) return
      pendingRef.current = null
      if (reason === null || stopped) return
      // An interrupted play is expected when pausing; stay silent.
      if (reason instanceof DOMException && reason.name === 'AbortError') return
      // A superseded generation, element, or sample must not surface stale errors.
      if (video.current !== record.element) return
      if (clock.current !== record.sample) return
      onError(START_FAILURE)
    }
    const timer = window.setInterval(() => {
      const element = video.current
      const sample = clock.current
      if (stopped || !element) return
      active = element
      if (!sample || sample.status.media_id !== mediaId || sample.status.handle !== handle) {
        if (!element.paused) element.pause()
        return
      }
      const target = videoClockTarget(sample.status, sample.timestamp, Date.now())
      element.muted = true
      element.volume = 0
      if (element.readyState >= 1 && Math.abs(element.currentTime - target.seconds) > SEEK_DRIFT_SECONDS) {
        element.currentTime = Math.min(target.seconds, Number.isFinite(element.duration) ? element.duration : target.seconds)
      }
      if (target.play && element.paused) {
        if (pendingRef.current !== null) return
        const record: PendingPlay = { element, mediaId, handle, sample }
        pendingRef.current = record
        let attempt: Promise<void>
        try {
          attempt = element.play()
        } catch (error) {
          settle(record, error)
          return
        }
        attempt.then(
          () => settle(record, null),
          (reason: unknown) => settle(record, reason),
        )
      } else if (!target.play) {
        element.pause()
      }
    }, POLL_MS)
    return () => {
      stopped = true
      window.clearInterval(timer)
      active?.pause()
    }
  }, [video, clock, mediaId, handle, enabled, onError])
}
