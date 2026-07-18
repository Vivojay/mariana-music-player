import type { MiniPlayerSnapshot } from './shared'

export type MiniPlayerControlProjection = {
  toggleAction: 'play' | 'pause' | null
  toggleLabel: 'Play' | 'Pause'
  previousEnabled: boolean
  nextEnabled: boolean
  unavailableReason: string | null
}

export function projectMiniPlayerControls(snapshot: MiniPlayerSnapshot): MiniPlayerControlProjection {
  const status = snapshot.playback
  const state = status?.state
  const activeState = state === 'playing' || state === 'paused' || state === 'crossfading'
  const available = Boolean(
    snapshot.ready
    && status?.media_id
    && activeState
    && status.policy?.playable !== false
    && !status.policy?.blocked,
  )
  const toggleAction = available
    ? state === 'paused' ? 'play' : state === 'playing' || state === 'crossfading' ? 'pause' : null
    : null
  const queuePosition = Number(status?.queue_position)
  const queueCount = Number(status?.queue_count)
  const queueBound = available
    && Number.isInteger(queuePosition)
    && Number.isInteger(queueCount)
    && queuePosition >= 1
    && queueCount >= queuePosition

  return {
    toggleAction,
    toggleLabel: toggleAction === 'pause' ? 'Pause' : 'Play',
    previousEnabled: Boolean(queueBound && queuePosition > 1),
    nextEnabled: Boolean(queueBound && queuePosition < queueCount),
    unavailableReason: available
      ? null
      : snapshot.diagnostic || status?.policy?.unavailable_reason || 'Playback controls unavailable',
  }
}
