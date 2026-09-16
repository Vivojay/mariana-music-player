import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReleaseSelection, type ReleaseSelectionApi } from './ReleaseSelection'
import { projectDiscoverySelection } from './discoveryProjection'
import type { BackendEvent, DiscoverySelection } from './shared'

afterEach(cleanup)

function harness(beginResult: Awaited<ReturnType<ReleaseSelectionApi['discoveryBegin']>> = { ok: true }) {
  let listener: ((event: BackendEvent) => void) | null = null
  const begin = vi.fn<ReleaseSelectionApi['discoveryBegin']>(async () => beginResult)
  const choose = vi.fn(async () => ({ ok: true }))
  const cancel = vi.fn(async () => ({ ok: true }))
  const api: ReleaseSelectionApi = {
    discoveryBegin: begin, discoveryChoose: choose, discoveryCancel: cancel,
    onEvent: (callback) => { listener = callback; return () => { listener = null } },
  }
  const view = render(<ReleaseSelection itemId="release:one" api={api} onClose={() => {}} />)
  const snapshot = (changes: Partial<DiscoverySelection> = {}): DiscoverySelection => ({
    schema_version: 1, request_id: begin.mock.calls[0][1], revision: 1,
    item_id: 'release:one', title: 'Chosen edition', artist: 'Artist', state: 'tracks',
    tracks: [{ id: 'b'.repeat(32), title: 'Recording', artist: 'Artist', position: 1, duration: 180 }],
    candidates: [], message: 'Choose a recording', ...changes,
  })
  const emit = (value: unknown) => act(() => listener?.({ event: 'discovery', timestamp: 1, payload: value as BackendEvent['payload'] }))
  return { ...view, begin, choose, cancel, snapshot, emit }
}

describe('explicit release selection', () => {
  it('loads metadata without executing commands and delegates only explicit typed choices', async () => {
    const { begin, choose, snapshot, emit } = harness()
    expect(begin).toHaveBeenCalledOnce()
    expect(screen.getByRole('region', { name: 'Release playback choices' })).toHaveFocus()
    expect(choose).not.toHaveBeenCalled()
    const tracks = snapshot()
    emit(tracks)
    expect(screen.getByText('1. Recording')).toBeVisible()
    fireEvent.keyDown(screen.getByRole('region', { name: 'Release playback choices' }), { key: 'Enter' })
    expect(choose).not.toHaveBeenCalled()
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Find versions of Recording' })))
    expect(choose).toHaveBeenCalledExactlyOnceWith(tracks.request_id, 1, 'b'.repeat(32), 'versions')
    choose.mockClear()
    emit(snapshot({ revision: 2, state: 'choices', candidates: [{
      id: 'c'.repeat(32), title: 'Actual alternate edition', artist: 'Performer', duration: 192,
      source: 'youtube', match: 'provider-result', playable: true,
    }] }))
    expect(screen.getByText(/not a verified edition match/)).toBeVisible()
    expect(choose).not.toHaveBeenCalled()
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Queue' })))
    expect(choose).toHaveBeenCalledExactlyOnceWith(tracks.request_id, 2, 'c'.repeat(32), 'queue')
  })

  it('ends the loading state on a rejected lookup and keeps close reachable', async () => {
    const { choose } = harness({ ok: false, error: 'Lookup unavailable' })
    await act(async () => {})
    expect(screen.getByRole('alert')).toHaveTextContent('Release lookup is unavailable')
    expect(screen.getByRole('region', { name: 'Release playback choices' })).toHaveAttribute('aria-busy', 'false')
    expect(screen.getByRole('status')).toHaveTextContent('No selection started; playback is unchanged')
    expect(screen.getByRole('button', { name: 'Close selection' })).toBeEnabled()
    expect(choose).not.toHaveBeenCalled()
  })

  it('rejects other sessions, old revisions, and malformed or private projections', () => {
    const { snapshot, emit, choose } = harness()
    emit(snapshot({ revision: 3 }))
    for (const value of [
      snapshot({ revision: 2, title: 'Old result' }),
      snapshot({ request_id: 'd'.repeat(32), revision: 4, title: 'Other session' }),
      snapshot({ revision: 5, item_id: 'release:other', title: 'Other card' }),
      { ...snapshot({ revision: 6 }), canonical_path: 'C:/private/file.mp3' },
      snapshot({ revision: 7, title: 'https://private.example/?secret=value' }),
    ]) emit(value)
    expect(screen.getByRole('heading', { name: 'Chosen edition' })).toBeVisible()
    expect(screen.queryByText('Old result')).not.toBeInTheDocument()
    expect(choose).not.toHaveBeenCalled()
  })

  it('disables blocked versions and cancels on close without any playback action', () => {
    const { snapshot, emit, unmount, cancel, choose } = harness()
    const state = snapshot({ state: 'choices', candidates: [{
      id: 'c'.repeat(32), title: 'Blocked version', artist: 'Artist', duration: null,
      source: 'local', match: 'metadata', playable: false,
    }] })
    emit(state)
    expect(screen.getByRole('button', { name: 'Play now' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Queue' })).toBeDisabled()
    expect(screen.getByText('Playback blocked or unavailable')).toBeVisible()
    unmount()
    expect(cancel).toHaveBeenCalledExactlyOnceWith(state.request_id)
    expect(choose).not.toHaveBeenCalled()
  })

  it('uses play intent only after a click, without optimistic playback state', async () => {
    const { snapshot, emit, choose } = harness()
    const state = snapshot({ state: 'choices', candidates: [{
      id: 'c'.repeat(32), title: 'Version', artist: 'Artist', duration: 180,
      source: 'local', match: 'recording-id', playable: true,
    }] })
    emit(state)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Play now' })))
    expect(choose).toHaveBeenCalledExactlyOnceWith(state.request_id, 1, 'c'.repeat(32), 'play')
    expect(screen.queryByText('Started selected version')).not.toBeInTheDocument()
    emit(snapshot({ revision: 2, state: 'complete', message: 'Started selected version' }))
    expect(screen.getByRole('status')).toHaveTextContent('Started selected version')
  })

  it('validates candidate bounds and drops unknown fields at the projection boundary', () => {
    const { snapshot } = harness()
    const state = snapshot({ state: 'choices', candidates: [{
      id: 'c'.repeat(32), title: 'Version', artist: 'Artist', duration: 180,
      source: 'local', match: 'metadata', playable: true,
    }] })
    expect(projectDiscoverySelection(state)).toEqual(state)
    for (const patch of [
      { duration: Infinity }, { source: 'arbitrary' }, { source: ['local'] }, { match: ['metadata'] },
      { url: 'https://private.example' }, { playable: 1 }, { id: '../file' },
    ]) {
      expect(projectDiscoverySelection({ ...state, candidates: [{ ...state.candidates[0], ...patch }] })).toBeNull()
    }
    expect(projectDiscoverySelection({ ...state, candidates: [state.candidates[0], state.candidates[0]] })).toBeNull()
  })
})
