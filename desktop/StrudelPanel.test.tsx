import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StrudelPanel } from './StrudelPanel'
import type { MarianaDesktopApi } from './shared'
import type { StrudelProjection } from './strudelProjects'

afterEach(cleanup)

const project = {
  project_id: 'a'.repeat(32), name: 'Night pattern', code: 'note("c3")', preview_seconds: 16,
  revision: 2, created_at: 1, updated_at: 2,
}

const projection: StrudelProjection = {
  schema_version: 1, open_requested: false, selected_id: project.project_id,
  projects: [project], limits: { max_projects: 100, max_code_bytes: 65536, max_preview_seconds: 60 },
}

function setup(onClose = vi.fn()) {
  const save = vi.fn(async () => ({ ok: true }))
  const preview = vi.fn(async () => ({ ok: true }))
  const remove = vi.fn(async () => ({ ok: true }))
  const api = {
    strudelSave: save,
    strudelPreview: preview,
    strudelDelete: remove,
  } as unknown as MarianaDesktopApi['backend']
  render(<StrudelPanel projection={projection} api={api} onClose={onClose} confirmDelete={() => true} />)
  return { save, preview, remove, onClose }
}

describe('Strudel pattern studio', () => {
  it('edits and saves through the typed backend boundary', async () => {
    const { save, preview } = setup()
    fireEvent.change(screen.getByRole('textbox', { name: 'Pattern source' }), { target: { value: 'note("d3")' } })
    expect(screen.getByRole('button', { name: 'Render & play' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(save).toHaveBeenCalledWith({
      project_id: project.project_id,
      name: project.name,
      code: 'note("d3")',
      preview_seconds: 16,
      revision: 2,
    }))
    expect(preview).not.toHaveBeenCalled()
  })

  it('renders only the unchanged saved revision', async () => {
    const { preview } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'Render & play' }))
    await waitFor(() => expect(preview).toHaveBeenCalledWith({
      project_id: project.project_id,
      name: project.name,
      code: project.code,
      preview_seconds: 16,
      revision: 2,
    }))
    expect(await screen.findByText('Preview sent to Mariana playback.')).toBeInTheDocument()
  })

  it('requires explicit deletion and forwards the bound revision', async () => {
    const { remove } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(remove).toHaveBeenCalledWith(project.project_id, project.revision))
  })

  it('closes with Escape instead of forwarding the key to playback', () => {
    const { onClose } = setup()
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })
})
