import type {
  CommandCatalogEntry,
  CommandCatalogForm,
  CommandCatalogOptions,
  CommandCatalogSnapshot,
} from './shared.js'

const ENTRY_KEYS = ['aliases', 'availability', 'canonical', 'category', 'forms', 'key', 'risk', 'summary']
const FORM_KEYS = ['argument_kinds', 'flags', 'tokens']
const RISKS = new Set(['read-only', 'state-changing', 'destructive', 'external-action'])
const PRIVATE_TEXT = /(?:https?:\/\/|[a-z]:[\\/]|\\\\)/iu

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort()
  return actual.length === keys.length && actual.every((key, index) => key === keys[index])
}

function safeText(value: unknown, maximum: number, allowEmpty = false): value is string {
  return typeof value === 'string'
    && value.length <= maximum
    && (allowEmpty || value.length > 0)
    && !Array.from(value).some((character) => {
      const code = character.charCodeAt(0)
      return code < 32 || code === 127
    })
    && !PRIVATE_TEXT.test(value)
}

function safeTextList(value: unknown, maximumItems: number): value is string[] {
  return Array.isArray(value)
    && value.length <= maximumItems
    && value.every((item) => safeText(item, 96))
}

function projectForm(value: unknown): CommandCatalogForm | null {
  if (!isRecord(value) || !hasExactKeys(value, FORM_KEYS)) return null
  if (
    !safeTextList(value.tokens, 8)
    || !safeTextList(value.argument_kinds, 8)
    || !safeTextList(value.flags, 16)
  ) return null
  return {
    tokens: [...value.tokens],
    argument_kinds: [...value.argument_kinds],
    flags: [...value.flags],
  }
}

function projectEntry(value: unknown): CommandCatalogEntry | null {
  if (!isRecord(value) || !hasExactKeys(value, ENTRY_KEYS)) return null
  if (
    !safeText(value.key, 96)
    || !safeText(value.canonical, 96)
    || !safeText(value.category, 96)
    || !safeText(value.summary, 256)
    || !safeText(value.risk, 32)
    || !RISKS.has(value.risk)
    || !safeTextList(value.aliases, 32)
    || !safeTextList(value.availability, 32)
    || !Array.isArray(value.forms)
    || value.forms.length > 64
  ) return null
  const forms = value.forms.map(projectForm)
  if (forms.some((form) => form === null)) return null
  return {
    key: value.key,
    canonical: value.canonical,
    category: value.category,
    summary: value.summary,
    risk: value.risk as CommandCatalogEntry['risk'],
    aliases: [...value.aliases],
    forms: forms as CommandCatalogForm[],
    availability: [...value.availability],
  }
}

export function validateCommandCatalogOptions(value: unknown): CommandCatalogOptions | null {
  if (value === undefined) return {}
  if (!isRecord(value)) return null
  const keys = Object.keys(value)
  if (keys.some((key) => !['includeCompatibility', 'typedPrefix'].includes(key))) return null
  if (value.includeCompatibility !== undefined && typeof value.includeCompatibility !== 'boolean') return null
  if (
    value.typedPrefix !== undefined
    && !safeText(value.typedPrefix, 64, true)
  ) return null
  return {
    ...(value.includeCompatibility === undefined ? {} : { includeCompatibility: value.includeCompatibility }),
    ...(value.typedPrefix === undefined ? {} : { typedPrefix: value.typedPrefix }),
  }
}

export function projectCommandCatalog(value: unknown): CommandCatalogSnapshot | null {
  if (!isRecord(value) || !hasExactKeys(value, ['entries', 'schema_version'])) return null
  if (value.schema_version !== 1 || !Array.isArray(value.entries) || value.entries.length > 256) return null
  const entries = value.entries.map(projectEntry)
  if (entries.some((entry) => entry === null)) return null
  return { schema_version: 1, entries: entries as CommandCatalogEntry[] }
}
