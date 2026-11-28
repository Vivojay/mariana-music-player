import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ListeningControls } from './ListeningControls'
import { equalizerState } from './equalizer.test'
import type { PlaybackStatus } from './shared'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('shows the voice setting on the main surface and submits a revision-bound change', async () => {
  const configure = vi.fn(async () => ({ ok: true, state: equalizerState({ deesser: 'gentle', revision: 4 }) }))
  vi.stubGlobal('mariana', { backend: {
    equalizerStatus: async () => ({ ok: true, state: equalizerState({ revision: 3 }) }),
    equalizerConfigure: configure,
    onEvent: () => () => {},
  } })
  const seek = vi.fn()
  const status = { source: 'podcast', position_seconds: 3 } as PlaybackStatus
  render(<ListeningControls ready status={status} seekEnabled onSeek={seek} />)
  const mode = screen.getByRole('combobox', { name: 'Soften sharp S sounds' })
  await waitFor(() => expect(mode).toHaveValue('off'))
  fireEvent.change(mode, { target: { value: 'gentle' } })
  await waitFor(() => expect(mode).toHaveValue('gentle'))
  expect(configure).toHaveBeenCalledWith({ operation: 'deesser', revision: 3, mode: 'gentle' })
  fireEvent.click(screen.getByRole('button', { name: 'Back 15s' }))
  fireEvent.click(screen.getByRole('button', { name: 'Forward 30s' }))
  expect(seek.mock.calls).toEqual([[0], [33]])
})
