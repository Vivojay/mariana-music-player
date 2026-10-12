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
const DEFAULT_SUGGESTION_LIMIT = 8
const MAXIMUM_SUGGESTION_LIMIT = 20

export type CommandSuggestionMatch =
  | 'canonical-exact'
  | 'canonical-prefix'
  | 'canonical-substring'
  | 'alias-exact'
  | 'alias-prefix'
  | 'alias-substring'

export type CommandSuggestion = Readonly<{
  key: string
  canonical: string
  display_label: string
  detail: string
  category: string
  risk: CommandCatalogEntry['risk']
  aliases: readonly string[]
  matched_alias: string | null
  match_kind: CommandSuggestionMatch
  flags_hint: string
  usage_hint: string
}>

export type CommandSuggestionRequest = Readonly<{
  typedPrefix: string
  generation: number
  limit?: number
}>

export type CommandSuggestionProjection = Readonly<{
  valid: boolean
  catalog_schema_version: 1
  request_generation: number | null
  typed_prefix: string | null
  suggestions: readonly CommandSuggestion[]
}>

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

function normalizedMatchText(value: string): string {
  return value.normalize('NFKC').toLowerCase()
}

function compareText(left: string, right: string): number {
  if (left < right) return -1
  if (left > right) return 1
  return 0
}

function suggestionLimit(value: number | undefined): number | null {
  if (value === undefined) return DEFAULT_SUGGESTION_LIMIT
  if (!Number.isSafeInteger(value) || value < 0) return null
  return Math.min(value, MAXIMUM_SUGGESTION_LIMIT)
}

function matchEntry(entry: CommandCatalogEntry, prefix: string): {
  rank: number
  matchedAlias: string | null
  kind: CommandSuggestionMatch
} | null {
  const canonical = normalizedMatchText(entry.canonical)
  if (prefix && canonical === prefix) return { rank: 0, matchedAlias: null, kind: 'canonical-exact' }
  if (!prefix || canonical.startsWith(prefix)) return { rank: 1, matchedAlias: null, kind: 'canonical-prefix' }
  if (prefix && canonical.includes(prefix)) return { rank: 2, matchedAlias: null, kind: 'canonical-substring' }

  const substringAliases = entry.aliases
    .map((alias) => ({ alias, normalized: normalizedMatchText(alias) }))
    .filter(({ normalized }) => normalized.includes(prefix))
    .sort((left, right) => {
      const exactDifference = Number(left.normalized !== prefix) - Number(right.normalized !== prefix)
      return exactDifference || compareText(left.normalized, right.normalized) || compareText(left.alias, right.alias)
    })
  const matched = substringAliases[0]
  if (!matched) return null
  const exact = matched.normalized === prefix
  const isPrefix = matched.normalized.startsWith(prefix)
  return {
    rank: exact ? 3 : isPrefix ? 4 : 5,
    matchedAlias: matched.alias,
    kind: exact ? 'alias-exact' : isPrefix ? 'alias-prefix' : 'alias-substring',
  }
}

/**
 * Convert validated backend catalog rows into bounded display metadata only.
 * The result intentionally contains no insertion text, replacement span, or action.
 */
export function projectCommandSuggestions(
  catalog: CommandCatalogSnapshot,
  request: CommandSuggestionRequest,
): CommandSuggestionProjection {
  const limit = suggestionLimit(request.limit)
  if (
    catalog.schema_version !== 1
    || !Number.isSafeInteger(request.generation)
    || request.generation < 0
    || !safeText(request.typedPrefix, 64, true)
    || limit === null
  ) {
    return {
      valid: false,
      catalog_schema_version: 1,
      request_generation: null,
      typed_prefix: null,
      suggestions: [],
    }
  }

  const prefix = normalizedMatchText(request.typedPrefix)
  const suggestions = catalog.entries
    .map((entry) => ({ entry, match: matchEntry(entry, prefix) }))
    .filter((candidate): candidate is typeof candidate & { match: NonNullable<typeof candidate.match> } => (
      candidate.match !== null
    ))
    .sort((left, right) => (
      left.match.rank - right.match.rank
      || compareText(normalizedMatchText(left.entry.category), normalizedMatchText(right.entry.category))
      || compareText(normalizedMatchText(left.entry.canonical), normalizedMatchText(right.entry.canonical))
      || compareText(left.entry.key, right.entry.key)
    ))
    .slice(0, limit)
    .map(({ entry, match }) => {
      const flags = Array.from(new Set(entry.forms.flatMap((form) => form.flags))).slice(0, 6)
      const usage = entry.forms
        .filter((form) => form.tokens.length > 0)
        .slice(0, 3)
        .map((form) => form.tokens.join(' '))
        .join(' | ')
      return {
        key: entry.key,
        canonical: entry.canonical,
        display_label: entry.canonical,
        detail: entry.summary,
        category: entry.category,
        risk: entry.risk,
        aliases: [...entry.aliases],
        matched_alias: match.matchedAlias,
        match_kind: match.kind,
        flags_hint: flags.join(' '),
        usage_hint: usage,
      }
    })

  return {
    valid: true,
    catalog_schema_version: 1,
    request_generation: request.generation,
    typed_prefix: request.typedPrefix,
    suggestions,
  }
}

export function isCommandSuggestionProjectionCurrent(
  projection: CommandSuggestionProjection,
  typedPrefix: string,
  generation: number,
): boolean {
  return projection.valid
    && Number.isSafeInteger(generation)
    && generation >= 0
    && safeText(typedPrefix, 64, true)
    && projection.request_generation === generation
    && projection.typed_prefix === typedPrefix
}
