import { useState } from 'react'
import type { MarianaDesktopApi } from './shared'
import { useModalFocusTrap } from './modalFocus'
import type { StrudelPreviewInput, StrudelProjection, StrudelSaveInput } from './strudelProjects'

import STARTER_CODE from '../res/strudel/starter.js?raw'

type Draft = StrudelSaveInput

function newDraft(): Draft {
  return { project_id: null, name: 'Untitled pattern', code: STARTER_CODE, preview_seconds: 16, revision: null }
}

function projectDraft(project: StrudelProjection['projects'][number]): Draft {
  return {
    project_id: project.project_id,
    name: project.name,
    code: project.code,
    preview_seconds: project.preview_seconds,
    revision: project.revision,
  }
}

export function StrudelPanel({
  projection,
  api,
  onClose,
  confirmDelete = (name) => window.confirm(`Delete “${name}”?`),
}: {
  projection: StrudelProjection | null
  api: MarianaDesktopApi['backend']
  onClose(): void
  confirmDelete?(name: string): boolean
}) {
  const [draft, setDraft] = useState<Draft>(() => {
    const selected = projection?.projects.find((project) => project.project_id === projection.selected_id)
      ?? projection?.projects[0]
    return selected ? projectDraft(selected) : newDraft()
  })
  const [savedDraft, setSavedDraft] = useState<Draft>(draft)
  const [pending, setPending] = useState<'save' | 'render' | 'delete' | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const dirty = JSON.stringify(draft) !== JSON.stringify(savedDraft)

  const close = () => {
    if (!dirty || window.confirm('Discard unsaved pattern changes?')) onClose()
  }
  const { dialogRef, containTabFocus } = useModalFocusTrap(true, { onOutsidePointer: close })

  const selectProject = (projectId: string) => {
    if (dirty && !window.confirm('Discard unsaved pattern changes?')) return
    const project = projection?.projects.find((candidate) => candidate.project_id === projectId)
    if (!project) return
    const next = projectDraft(project)
    setDraft(next)
    setSavedDraft(next)
    setMessage(null)
  }

  const createProject = () => {
    if (dirty && !window.confirm('Discard unsaved pattern changes?')) return
    const next = newDraft()
    setDraft(next)
    setSavedDraft({ ...next, name: '', code: '' })
    setMessage('Name the pattern, edit it, then save before rendering.')
  }

  const save = async () => {
    if (pending) return
    setPending('save')
    setMessage(null)
    try {
      const result = await api.strudelSave(draft)
      if (!result.ok) {
        setMessage(result.error || 'Pattern could not be saved')
        return
      }
      const snapshot = await api.snapshot()
      const project = snapshot.strudel?.projects.find(item => draft.project_id
        ? item.project_id === draft.project_id : item.name === draft.name.normalize('NFC').trim())
      if (!project) {
        setMessage('Pattern saved. Reopen the project to load its current revision.')
        return
      }
      const next = projectDraft(project)
      setDraft(next)
      setSavedDraft(next)
      setMessage('Pattern saved.')
    } catch {
      setMessage('Pattern could not be saved')
    } finally {
      setPending(null)
    }
  }

  const preview = async () => {
    if (pending || dirty || !draft.project_id || draft.revision === null) return
    setPending('render')
    setMessage('Rendering a bounded preview…')
    try {
      const result = await api.strudelPreview(draft as StrudelPreviewInput)
      setMessage(result.ok ? 'Preview sent to Mariana playback.' : result.error || 'Pattern could not be rendered')
    } catch {
      setMessage('Pattern could not be rendered')
    } finally {
      setPending(null)
    }
  }

  const remove = async () => {
    if (pending || !draft.project_id || draft.revision === null || !confirmDelete(draft.name)) return
    setPending('delete')
    setMessage(null)
    try {
      const result = await api.strudelDelete(draft.project_id, draft.revision)
      if (result.ok) {
        const next = newDraft()
        setDraft(next)
        setSavedDraft(next)
      }
      setMessage(result.ok ? 'Pattern deleted.' : result.error || 'Pattern could not be deleted')
    } catch {
      setMessage('Pattern could not be deleted')
    } finally {
      setPending(null)
    }
  }

  return (
    <section
      ref={dialogRef}
      className="studio-dialog strudel-panel"
      role="dialog"
      aria-modal="true"
      aria-label="Strudel pattern studio"
      tabIndex={-1}
      onKeyDown={(event) => {
        event.stopPropagation()
        containTabFocus(event)
        if (event.key === 'Escape') {
          event.preventDefault()
          close()
        }
      }}
    >
      <header>
        <div><small>LOCAL COMPOSITION</small><h1>Strudel pattern studio</h1></div>
        <button type="button" aria-label="Close pattern studio" onClick={close}>Close</button>
      </header>
      <div className="strudel-toolbar">
        <label>
          <span>Saved project</span>
          <select value={draft.project_id ?? ''} onChange={(event) => selectProject(event.target.value)} disabled={Boolean(pending)}>
            {!draft.project_id && <option value="">New unsaved project</option>}
            {projection?.projects.map((project) => <option key={project.project_id} value={project.project_id}>{project.name}</option>)}
          </select>
        </label>
        <button type="button" onClick={createProject} disabled={Boolean(pending)}>New</button>
        <button type="button" onClick={() => void save()} disabled={Boolean(pending) || (!dirty && Boolean(draft.project_id))}>Save</button>
        <button type="button" onClick={() => void preview()} disabled={Boolean(pending) || dirty || !draft.project_id}>
          {pending === 'render' ? 'Rendering…' : 'Render & play'}
        </button>
        <button type="button" className="danger" onClick={() => void remove()} disabled={Boolean(pending) || !draft.project_id}>Delete</button>
      </div>
      <div className="strudel-fields">
        <label><span>Project name</span><input autoFocus disabled={Boolean(pending)} value={draft.name} maxLength={120} onChange={(event) => setDraft((value) => ({ ...value, name: event.target.value }))} /></label>
        <label><span>Preview seconds</span><input type="number" disabled={Boolean(pending)} min={1} max={60} step={1} value={draft.preview_seconds} onChange={(event) => setDraft((value) => ({ ...value, preview_seconds: Number(event.target.value) }))} /></label>
      </div>
      <label className="strudel-editor-label">
        <span>Pattern source</span>
        <textarea
          aria-label="Pattern source"
          spellCheck={false}
          disabled={Boolean(pending)}
          value={draft.code}
          onChange={(event) => setDraft((value) => ({ ...value, code: event.target.value }))}
          onKeyDown={(event) => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
              event.preventDefault()
              void save()
            }
            if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
              event.preventDefault()
              void preview()
            }
          }}
        />
      </label>
      <footer>
        <p>{message || (dirty ? 'Unsaved changes. Save before rendering.' : 'Ready to render through Mariana’s playback pipeline.')}</p>
        <small>Preview rendering is bounded to 60 seconds. Sample patterns may fetch Strudel’s official sample resources; synth-only patterns can render without publishing project source.</small>
      </footer>
    </section>
  )
}
