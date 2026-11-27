import '../web/player/command-match.js'
import { projectCommandSuggestions, type CommandSuggestion, type CommandSuggestionRequest } from './commandCatalog'
import type { CommandCatalogSnapshot } from './shared'

type GrammarRow = {
  path: string
  aliases?: readonly string[]
  flags?: readonly string[]
  arguments?: readonly string[]
  surface?: string
  description?: string
}
type Match = { label: string; start: number; end: number; value: string; correction: boolean; description: string }
type Matcher = { suggest: (text: string, cursor: number, grammar: GrammarRow[]) => Match[] }
const matcher = (globalThis as typeof globalThis & { MarianaCommandMatch: Matcher }).MarianaCommandMatch
const manifests = import.meta.glob<{ commands: GrammarRow[] }>('../mariana/command_grammar_*.json', { eager: true, import: 'default' })
const nativeRows = Object.values(manifests).flatMap(manifest => manifest.commands.filter(row => row.surface !== 'portable'))
const cache = new WeakMap<CommandCatalogSnapshot, GrammarRow[]>()

function grammar(catalog: CommandCatalogSnapshot) {
  let rows = cache.get(catalog)
  if (!rows) {
    rows = catalog.entries.flatMap(entry => [
      { path: entry.canonical, aliases: entry.aliases, description: entry.summary },
      ...entry.forms.map(form => ({
        path: [entry.canonical, ...form.tokens].join(' '),
        flags: form.flags, arguments: form.argument_kinds, description: entry.summary,
      })),
    ] as GrammarRow[])
    rows.push(...nativeRows)
    cache.set(catalog, rows)
  }
  return rows
}

function metadata(catalog: CommandCatalogSnapshot, label: string) {
  const normalized = label.toLowerCase()
  const contains = (key: string) => normalized === key.toLowerCase() || normalized.startsWith(key.toLowerCase() + ' ')
  const entry = catalog.entries.find(item => [item.canonical, ...item.aliases].some(head => {
    if (head.toLowerCase() === normalized) return true
    return item.forms.some(form => [head, ...form.tokens].join(' ').toLowerCase() === normalized)
  }))
  if (entry) return entry
  const rule = nativeRows.filter(row => [row.path, ...(row.aliases || [])].some(contains))
    .sort((a, b) => b.path.length - a.path.length)[0]
  return { key: rule?.path || label, canonical: rule?.path || label, summary: rule?.description || '',
    category: 'Native commands', risk: 'unspecified' as const, aliases: rule?.aliases || [] }
}

/** The header explores public grammar. Accepting an item edits only this field. */
export function exploreCommandSuggestions(catalog: CommandCatalogSnapshot, request: CommandSuggestionRequest) {
  const base = projectCommandSuggestions(catalog, request)
  const text = request.typedPrefix
  if (!base.valid || !/^[\w .*/?+=-]+$/u.test(text)) return base
  const syntax: CommandSuggestion[] = []
  for (const match of matcher.suggest(text, text.length, grammar(catalog))) {
    const label = (text.slice(0, match.start) + match.value + text.slice(match.end)).trim()
    const entry = metadata(catalog, label)
    syntax.push({
      key: 'grammar/' + label, canonical: entry.canonical, display_label: label, detail: match.description || entry.summary,
      category: entry.category, risk: entry.risk, aliases: [...entry.aliases], matched_alias: null,
      match_kind: match.correction ? 'correction' : 'grammar',
    })
  }
  // Once a word is complete, prioritize the next grammar slot over the parent
  // entry. For a head prefix, keep the catalog's canonical/alias ranking and
  // interleave previously unseen native spellings.
  const seen = new Set<string>()
  const suggestions: CommandSuggestion[] = []
  function add(row?: CommandSuggestion) {
    const label = row?.display_label.toLowerCase()
    if (row && label && !seen.has(label)) {
      seen.add(label)
      suggestions.push(row)
    }
  }
  if (text.trimStart().includes(' ')) {
    syntax.forEach(add)
    base.suggestions.forEach(add)
  } else {
    for (let i = 0; i < Math.max(syntax.length, base.suggestions.length); i++) {
      add(base.suggestions[i])
      add(syntax[i])
    }
  }
  return { ...base, suggestions: suggestions.slice(0, request.limit ?? 8) }
}
