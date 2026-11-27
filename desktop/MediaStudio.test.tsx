import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import practiceSheet from '../res/karaoke/practice-duet.json'
import { MediaStudio } from './MediaStudio'
import { projectStudioResult, type StudioAction, type StudioResult } from './mediaStudioProtocol'
import type { PlaybackStatus } from './shared'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function recording(position: number, mediaId = 'demo'): PlaybackStatus {
  return { media_id: mediaId, title: mediaId, position_seconds: position, duration_seconds: 6, state: 'paused' } as PlaybackStatus
}

function openPanel(name: string) {
  fireEvent.click(screen.getByRole('button', { name }))
}

it('highlights the current practice word and displays both singers when their parts overlap', async () => {
  const mediaStudio = vi.fn(async (intent: StudioAction) =>
    projectStudioResult(intent.action, { media_id: 'demo', available: true, score: 1, sheet: practiceSheet }))
  vi.stubGlobal('mariana', { backend: { mediaStudio } })
  const view = render(<MediaStudio ready status={recording(0.5)} />)
  openPanel('Karaoke')
  const voices = await screen.findByLabelText('Synchronized singer parts')
  const highlighted = () => Array.from(voices.querySelectorAll('[aria-current="true"]'), word => word.textContent?.trim())
  expect(highlighted()).toEqual(['Ah'])
  view.rerender(<MediaStudio ready status={recording(1.2)} />)
  expect(highlighted()).toEqual(['Ooh'])
  view.rerender(<MediaStudio ready status={recording(2.1)} />)
  expect(highlighted()).toEqual(['Oh'])
  view.rerender(<MediaStudio ready status={recording(3.6)} />)
  expect(within(voices).getByRole('heading', { name: 'Alto' })).toBeVisible()
  expect(within(voices).getByRole('heading', { name: 'Tenor' })).toBeVisible()
  expect(highlighted()).toHaveLength(2)
  expect(mediaStudio).toHaveBeenCalledTimes(1)
})

it('shares the displayed selection, then ignores a late export result for a previous recording', async () => {
  let finishExport!: (result: StudioResult) => void
  const mediaStudio = vi.fn(async (intent: StudioAction): Promise<StudioResult> => {
    if (intent.action === 'clip.status') return projectStudioResult(intent.action, {
      media_id: intent.mediaId, available: true, start_seconds: 0, end_seconds: 2,
    })
    if (intent.action === 'clip.share') return { ok: true, jobId: 'a'.repeat(32) }
    if (intent.action === 'clip.job') return { ok: true, phase: 'ready', message: 'Shared selection' }
    if (intent.action === 'clip.export') return new Promise(resolve => { finishExport = resolve })
    throw new Error('Unexpected studio action')
  })
  vi.stubGlobal('mariana', { backend: { mediaStudio } })
  const view = render(<MediaStudio ready status={recording(0.5)} />)
  openPanel('Share clip')
  const share = screen.getByRole('button', { name: 'Prepare & share' })
  await waitFor(() => expect(share).toBeEnabled())
  fireEvent.click(share)
  expect(await screen.findByText('Shared selection')).toBeVisible()
  expect(mediaStudio).toHaveBeenCalledWith({ action: 'clip.share', mediaId: 'demo', start: 0, end: 2, format: 'm4a' })
  openPanel('Save clip…')
  view.rerender(<MediaStudio ready status={recording(1, 'another')} />)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Prepare & share' })).toBeEnabled())
  await act(async () => { finishExport({ ok: false, error: 'Old recording export' }) })
  expect(screen.queryByText('Old recording export')).toBeNull()
})
