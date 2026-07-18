import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MiniPlayerApp from './MiniPlayerApp'
import type { MarianaMiniPlayerApi, MiniPlayerSnapshot } from './shared'

vi.mock('./PlaybackStatusBar', () => ({
  PlaybackStatusBar: ({ unavailableReason }: { unavailableReason?: string | null }) => (
    <div aria-label="Playback status">{unavailableReason}</div>
  ),
}))

const showMain = vi.fn(async () => undefined)
const hide = vi.fn(async () => undefined)
let snapshot: MiniPlayerSnapshot
let receiveSnapshot: ((next: MiniPlayerSnapshot) => void) | undefined

beforeEach(() => {
  showMain.mockClear()
  hide.mockClear()
  receiveSnapshot = undefined
  snapshot = { ready: false, diagnostic: null, playback: null }
  const api: MarianaMiniPlayerApi = {
    snapshot: async () => snapshot,
    onSnapshot: (callback) => {
      receiveSnapshot = callback
      return () => { receiveSnapshot = undefined }
    },
    showMain,
    hide,
    platform: 'win32',
  }
  Object.defineProperty(window, 'marianaMini', { configurable: true, value: api })
})

afterEach(cleanup)

describe('Mini-player lifecycle surface', () => {
  it('restores its safe snapshot and receives lifecycle updates', async () => {
    render(<MiniPlayerApp />)

    expect(screen.getByLabelText('Playback status')).toHaveTextContent('Waiting for backend')
    await waitFor(() => expect(receiveSnapshot).toBeDefined())
    act(() => receiveSnapshot?.({ ready: false, diagnostic: 'Backend unavailable', playback: null }))
    expect(screen.getByLabelText('Playback status')).toHaveTextContent('Backend unavailable')
  })

  it('does not let a delayed initial snapshot replace a newer streamed state', async () => {
    let resolveInitial: ((value: MiniPlayerSnapshot) => void) | undefined
    window.marianaMini.snapshot = () => new Promise((resolve) => { resolveInitial = resolve })
    render(<MiniPlayerApp />)
    await waitFor(() => expect(receiveSnapshot).toBeDefined())

    act(() => receiveSnapshot?.({ ready: false, diagnostic: 'Current backend state', playback: null }))
    await act(async () => resolveInitial?.({ ready: false, diagnostic: 'Stale initial state', playback: null }))

    expect(screen.getByLabelText('Playback status')).toHaveTextContent('Current backend state')
  })

  it('shows the main window and hides through narrow lifecycle actions', () => {
    render(<MiniPlayerApp />)

    fireEvent.click(screen.getByRole('button', { name: 'Show Mariana' }))
    fireEvent.click(screen.getByRole('button', { name: 'Hide Mini-player' }))
    fireEvent.keyDown(window, { key: 'Escape' })

    expect(showMain).toHaveBeenCalledOnce()
    expect(hide).toHaveBeenCalledTimes(2)
  })
})
