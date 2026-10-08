export const STRUDEL_MAX_CODE_BYTES = 64 * 1024
export const STRUDEL_MAX_PREVIEW_SECONDS = 60
export const STRUDEL_MAX_RENDERED_FILES = 24
export const STRUDEL_MAX_RENDERED_BYTES = 192 * 1024 * 1024

export type StrudelProject = {
  project_id: string
  name: string
  code: string
  preview_seconds: number
  revision: number
  created_at: number
  updated_at: number
}

export type StrudelProjection = {
  schema_version: 1
  open_requested: boolean
  selected_id: string | null
  projects: StrudelProject[]
  limits: {
    max_projects: number
    max_code_bytes: number
    max_preview_seconds: number
  }
}

export type StrudelSaveInput = {
  project_id: string | null
  name: string
  code: string
  preview_seconds: number
  revision: number | null
}

export type StrudelPreviewInput = {
  project_id: string
  name: string
  code: string
  preview_seconds: number
  revision: number
}

export type StrudelRenderedFile = {
  name: string
  size: number
  mtimeMs: number
}

const projectId = /^[0-9a-f]{32}$/
const renderedFileName = /^[0-9a-f]{32}-[0-9a-f]{64}\.wav$/

function validProject(value: unknown): value is StrudelProject {
  if (!value || typeof value !== 'object') return false
  const project = value as Record<string, unknown>
  return typeof project.project_id === 'string'
    && projectId.test(project.project_id)
    && typeof project.name === 'string'
    && project.name.trim().length > 0
    && project.name.length <= 120
    && typeof project.code === 'string'
    && new TextEncoder().encode(project.code).byteLength <= STRUDEL_MAX_CODE_BYTES
    && Number.isSafeInteger(project.preview_seconds)
    && Number(project.preview_seconds) >= 1
    && Number(project.preview_seconds) <= STRUDEL_MAX_PREVIEW_SECONDS
    && Number.isSafeInteger(project.revision)
    && Number(project.revision) >= 1
    && Number.isFinite(project.created_at)
    && Number.isFinite(project.updated_at)
}

export function projectStrudelProjection(value: unknown): StrudelProjection | null {
  if (!value || typeof value !== 'object') return null
  const candidate = value as Record<string, unknown>
  const limits = candidate.limits as Record<string, unknown> | null
  if (
    candidate.schema_version !== 1
    || typeof candidate.open_requested !== 'boolean'
    || !(candidate.selected_id === null || (typeof candidate.selected_id === 'string' && projectId.test(candidate.selected_id)))
    || !Array.isArray(candidate.projects)
    || candidate.projects.length > 100
    || !candidate.projects.every(validProject)
    || !limits
    || !Number.isSafeInteger(limits.max_projects)
    || !Number.isSafeInteger(limits.max_code_bytes)
    || !Number.isSafeInteger(limits.max_preview_seconds)
    || limits.max_projects !== 100
    || limits.max_code_bytes !== STRUDEL_MAX_CODE_BYTES
    || limits.max_preview_seconds !== STRUDEL_MAX_PREVIEW_SECONDS
  ) return null
  const projects = candidate.projects as StrudelProject[]
  const identities = new Set(projects.map((project) => project.project_id))
  if (identities.size !== projects.length || (candidate.selected_id && !identities.has(candidate.selected_id))) return null
  return {
    schema_version: 1,
    open_requested: candidate.open_requested,
    selected_id: candidate.selected_id as string | null,
    projects: projects.map((project) => ({ ...project })),
    limits: {
      max_projects: 100,
      max_code_bytes: STRUDEL_MAX_CODE_BYTES,
      max_preview_seconds: STRUDEL_MAX_PREVIEW_SECONDS,
    },
  }
}

export function durableStrudelProjection(value: StrudelProjection): StrudelProjection {
  return { ...value, open_requested: false, selected_id: value.selected_id }
}

export function validStrudelSaveInput(value: unknown): value is StrudelSaveInput {
  if (!value || typeof value !== 'object') return false
  const input = value as Record<string, unknown>
  return (input.project_id === null || (typeof input.project_id === 'string' && projectId.test(input.project_id)))
    && typeof input.name === 'string'
    && input.name.trim().length > 0
    && input.name.length <= 120
    && typeof input.code === 'string'
    && input.code.trim().length > 0
    && new TextEncoder().encode(input.code).byteLength <= STRUDEL_MAX_CODE_BYTES
    && Number.isSafeInteger(input.preview_seconds)
    && Number(input.preview_seconds) >= 1
    && Number(input.preview_seconds) <= STRUDEL_MAX_PREVIEW_SECONDS
    && (input.revision === null || (Number.isSafeInteger(input.revision) && Number(input.revision) >= 1))
    && ((input.project_id === null) === (input.revision === null))
}

export function validStrudelPreviewInput(value: unknown): value is StrudelPreviewInput {
  return validStrudelSaveInput(value)
    && value.project_id !== null
    && value.revision !== null
}

export function strudelRenderedFilesToPrune(
  entries: StrudelRenderedFile[],
  keepName: string,
): string[] {
  const candidates = entries
    .filter((entry) => renderedFileName.test(entry.name)
      && Number.isSafeInteger(entry.size)
      && entry.size >= 0
      && Number.isFinite(entry.mtimeMs))
    .sort((left, right) => right.mtimeMs - left.mtimeMs || left.name.localeCompare(right.name))
  const active = candidates.find((entry) => entry.name === keepName)
  let retainedFiles = active ? 1 : 0
  let retainedBytes = active?.size ?? 0
  const pruned: string[] = []
  for (const entry of candidates) {
    if (entry.name === keepName) continue
    if (retainedFiles >= STRUDEL_MAX_RENDERED_FILES
      || retainedBytes + entry.size > STRUDEL_MAX_RENDERED_BYTES) {
      pruned.push(entry.name)
      continue
    }
    retainedFiles += 1
    retainedBytes += entry.size
  }
  return pruned
}
