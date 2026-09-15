// Only these backend projections contribute to the Mini-player snapshot.
const snapshotEvents = new Set([
  'playback', 'hotspots', 'artwork', 'video', 'desktop-download',
  'ready', 'fatal-error', 'shutdown-ack',
])

export function shouldDeliverMiniSnapshot(
  visible: boolean,
  minimized: boolean,
  event?: string,
): boolean {
  return visible && !minimized && (event === undefined || snapshotEvents.has(event))
}
