import { PlaybackStatusBar } from './PlaybackStatusBar'
import type { PlaybackStatus } from './shared'

type MiniPlayerNowPlayingProps = {
  status: PlaybackStatus | null
  unavailableReason: string
}

export function MiniPlayerNowPlaying({ status, unavailableReason }: MiniPlayerNowPlayingProps) {
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
    </section>
  )
}
