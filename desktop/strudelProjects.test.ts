import { describe, expect, it } from 'vitest'
import {
  projectStrudelProjection,
  strudelRenderedFilesToPrune,
  validStrudelPreviewInput,
  validStrudelSaveInput,
} from './strudelProjects'

const project = {
  project_id: 'a'.repeat(32),
  name: 'Night pattern',
  code: 'note("c3")',
  preview_seconds: 16,
  revision: 2,
  created_at: 1,
  updated_at: 2,
}

describe('Strudel project projection', () => {
  it('accepts a bounded revisioned projection and copies it', () => {
    const value = {
      schema_version: 1,
      open_requested: true,
      selected_id: project.project_id,
      projects: [project],
      limits: { max_projects: 100, max_code_bytes: 65536, max_preview_seconds: 60 },
    }
    const result = projectStrudelProjection(value)
    expect(result).toEqual(value)
    expect(result?.projects[0]).not.toBe(project)
  })

  it('rejects duplicate, unbounded, and dangling project data', () => {
    const base = {
      schema_version: 1,
      open_requested: false,
      selected_id: null,
      projects: [project],
      limits: { max_projects: 100, max_code_bytes: 65536, max_preview_seconds: 60 },
    }
    expect(projectStrudelProjection({ ...base, projects: [project, project] })).toBeNull()
    expect(projectStrudelProjection({ ...base, selected_id: 'b'.repeat(32) })).toBeNull()
    expect(projectStrudelProjection({ ...base, projects: [{ ...project, preview_seconds: 61 }] })).toBeNull()
  })

  it('binds saves and previews to valid project revisions', () => {
    expect(validStrudelSaveInput({ ...project, project_id: null, revision: null })).toBe(true)
    expect(validStrudelSaveInput({ ...project, project_id: null, revision: 1 })).toBe(false)
    expect(validStrudelPreviewInput(project)).toBe(true)
    expect(validStrudelPreviewInput({ ...project, project_id: null, revision: null })).toBe(false)
  })
})

describe('rendered pattern preview retention', () => {
  it('retains the active render while enforcing file and byte limits', () => {
    const active = `${'a'.repeat(32)}-${'b'.repeat(64)}.wav`
    const entries = Array.from({ length: 26 }, (_, index) => ({
      name: `${index.toString(16).padStart(32, '0')}-${'c'.repeat(64)}.wav`,
      size: 9 * 1024 * 1024,
      mtimeMs: 100 - index,
    }))
    entries.push({ name: active, size: 9 * 1024 * 1024, mtimeMs: 0 })
    entries.push({ name: 'unrelated.wav', size: 1, mtimeMs: 200 })

    const pruned = strudelRenderedFilesToPrune(entries, active)

    expect(pruned).not.toContain(active)
    expect(pruned).not.toContain('unrelated.wav')
    expect(pruned.length).toBeGreaterThan(0)
  })
})
