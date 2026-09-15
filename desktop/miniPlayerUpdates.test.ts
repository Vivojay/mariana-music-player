import { describe, expect, it } from 'vitest'
import { shouldDeliverMiniSnapshot } from './miniPlayerUpdates'

describe('Mini-player snapshot delivery', () => {
  it.each(['playback', 'hotspots', 'artwork', 'video', 'desktop-download', 'ready', 'fatal-error', 'shutdown-ack'])(
    'delivers current %s state to a presented window', (event) => {
      expect(shouldDeliverMiniSnapshot(true, false, event)).toBe(true)
    },
  )

  it.each(['homepage', 'lyrics', 'equalizer', 'control-result', 'crossfade', 'desktop-notice', 'strudel', 'sleep'])(
    'does not repeat unchanged Mini state for %s', (event) => {
      expect(shouldDeliverMiniSnapshot(true, false, event)).toBe(false)
    },
  )

  it('keeps hidden and minimized windows dormant even for explicit refreshes', () => {
    for (const event of [undefined, 'playback', 'video', 'ready']) {
      expect(shouldDeliverMiniSnapshot(false, false, event)).toBe(false)
      expect(shouldDeliverMiniSnapshot(true, true, event)).toBe(false)
    }
  })

  it('allows a complete fresh projection when a window is shown or restored', () => {
    expect(shouldDeliverMiniSnapshot(true, false)).toBe(true)
  })
})
