import { describe, expect, it } from 'vitest'
import {
  isCommandSuggestionProjectionCurrent,
  projectCommandCatalog,
  projectCommandSuggestions,
  validateCommandCatalogOptions,
} from './commandCatalog'
import type { CommandCatalogEntry, CommandCatalogSnapshot } from './shared'

const entry = {
  key: 'now',
  canonical: 'now',
  category: 'Playback',
  summary: 'Show current playback status',
  risk: 'read-only',
  aliases: ['.'],
  forms: [{ tokens: ['current'], argument_kinds: [], flags: [] }],
  availability: ['backend-ready'],
}

const catalogEntry = (
  canonical: string,
  category: string,
  aliases: string[] = [],
  key = canonical,
): CommandCatalogEntry => ({
  key,
  canonical,
  category,
  summary: `Describe ${canonical}`,
  risk: canonical === 'rm' ? 'destructive' : 'read-only',
  aliases,
  forms: [],
  availability: [],
})

const catalog = (...entries: CommandCatalogEntry[]): CommandCatalogSnapshot => ({
  schema_version: 1,
  entries,
})

describe('command catalog runtime projection', () => {
  it('accepts and copies the versioned public shape', () => {
    const raw = { schema_version: 1, entries: [entry] }
    const projected = projectCommandCatalog(raw)

    expect(projected).toEqual(raw)
    expect(projected).not.toBe(raw)
    expect(projected?.entries[0]).not.toBe(entry)
  })

  it.each([
    { schema_version: 2, entries: [entry] },
    { schema_version: 1, entries: [{ ...entry, handler: 'private' }] },
    { schema_version: 1, entries: [{ ...entry, summary: 'https://private.invalid' }] },
    { schema_version: 1, entries: [{ ...entry, risk: 'execute-anything' }] },
    { schema_version: 1, entries: [{ ...entry, forms: [{ tokens: [42], argument_kinds: [], flags: [] }] }] },
  ])('rejects malformed or unsafe payloads', (value) => {
    expect(projectCommandCatalog(value)).toBeNull()
  })

  it('validates only bounded explicit request options', () => {
    expect(validateCommandCatalogOptions(undefined)).toEqual({})
    expect(validateCommandCatalogOptions({ includeCompatibility: true, typedPrefix: '.' })).toEqual({
      includeCompatibility: true,
      typedPrefix: '.',
    })
    expect(validateCommandCatalogOptions({ unknown: true })).toBeNull()
    expect(validateCommandCatalogOptions({ includeCompatibility: 'yes' })).toBeNull()
    expect(validateCommandCatalogOptions({ typedPrefix: 'now\n' })).toBeNull()
    expect(validateCommandCatalogOptions({ typedPrefix: 'x'.repeat(65) })).toBeNull()
  })
})

describe('renderer command suggestion projection', () => {
  it('filters case-insensitively and ranks canonical exact matches before prefixes', () => {
    const projected = projectCommandSuggestions(
      catalog(
        catalogEntry('playlist', 'Playlists'),
        catalogEntry('play', 'Playback'),
        catalogEntry('pause', 'Playback'),
      ),
      { typedPrefix: 'PLAY', generation: 3 },
    )

    expect(projected.valid).toBe(true)
    expect(projected.suggestions.map(({ canonical, match_kind }) => [canonical, match_kind])).toEqual([
      ['play', 'canonical-exact'],
      ['playlist', 'canonical-prefix'],
    ])
  })

  it('matches only aliases present in the safe catalog and preserves prefixed alias labels', () => {
    const withoutCompatibility = projectCommandSuggestions(
      catalog(catalogEntry('now', 'Playback')),
      { typedPrefix: '.', generation: 1 },
    )
    const withCompatibility = projectCommandSuggestions(
      catalog(catalogEntry('now', 'Playback', ['.'])),
      { typedPrefix: '.', generation: 2 },
    )

    expect(withoutCompatibility.suggestions).toEqual([])
    expect(withCompatibility.suggestions).toEqual([
      expect.objectContaining({
        canonical: 'now',
        display_label: 'now',
        matched_alias: '.',
        match_kind: 'alias-exact',
      }),
    ])
    expect(withCompatibility.suggestions[0]).not.toHaveProperty('insertion_text')
    expect(withCompatibility.suggestions[0]).not.toHaveProperty('action')
  })

  it('preserves destructive risk as display-only metadata', () => {
    const destructive = {
      ...catalogEntry('playlist delete', 'Playlists'),
      risk: 'destructive' as const,
    }
    const projected = projectCommandSuggestions(
      catalog(destructive),
      { typedPrefix: 'playlist d', generation: 3 },
    )

    expect(projected.suggestions).toEqual([
      expect.objectContaining({ canonical: 'playlist delete', risk: 'destructive' }),
    ])
    expect(projected.suggestions[0]).not.toHaveProperty('action')
    expect(projected.suggestions[0]).not.toHaveProperty('confirmation_handler')
    expect(projected.suggestions[0]).not.toHaveProperty('insertion_text')
  })

  it('sorts equal matches deterministically without mutating catalog order', () => {
    const entries = [
      catalogEntry('zoom', 'Settings'),
      catalogEntry('zebra', 'Playback'),
      catalogEntry('zap', 'Playback'),
    ]
    const projected = projectCommandSuggestions(catalog(...entries), { typedPrefix: 'z', generation: 4 })

    expect(projected.suggestions.map(({ canonical }) => canonical)).toEqual(['zap', 'zebra', 'zoom'])
    expect(entries.map(({ canonical }) => canonical)).toEqual(['zoom', 'zebra', 'zap'])
  })

  it('ranks canonical matches ahead of alias matches and aliases deterministically', () => {
    const projected = projectCommandSuggestions(
      catalog(
        catalogEntry('north', 'Playback', ['n']),
        catalogEntry('n', 'Diagnostics'),
        catalogEntry('status', 'Diagnostics', ['near', 'next']),
      ),
      { typedPrefix: 'n', generation: 5 },
    )

    expect(projected.suggestions.map(({ canonical, matched_alias, match_kind }) => (
      [canonical, matched_alias, match_kind]
    ))).toEqual([
      ['n', null, 'canonical-exact'],
      ['north', null, 'canonical-prefix'],
      ['status', 'near', 'alias-prefix'],
    ])
  })

  it('returns a bounded stable set for empty input and an empty set for no matches', () => {
    const entries = Array.from({ length: 25 }, (_, index) => (
      catalogEntry(`command-${String(index).padStart(2, '0')}`, 'Diagnostics')
    ))
    const defaultProjection = projectCommandSuggestions(catalog(...entries), { typedPrefix: '', generation: 6 })
    const maximumProjection = projectCommandSuggestions(
      catalog(...entries),
      { typedPrefix: '', generation: 7, limit: 99 },
    )
    const noMatches = projectCommandSuggestions(catalog(...entries), { typedPrefix: 'zzz', generation: 8 })

    expect(defaultProjection.suggestions).toHaveLength(8)
    expect(maximumProjection.suggestions).toHaveLength(20)
    expect(noMatches.suggestions).toEqual([])
  })

  it('rejects malformed request state without echoing unsafe input', () => {
    const snapshot = catalog(catalogEntry('now', 'Playback'))

    for (const request of [
      { typedPrefix: 'now\n', generation: 1 },
      { typedPrefix: 'https://private.invalid', generation: 1 },
      { typedPrefix: 'x'.repeat(65), generation: 1 },
      { typedPrefix: 'n', generation: -1 },
      { typedPrefix: 'n', generation: 1, limit: -1 },
    ]) {
      expect(projectCommandSuggestions(snapshot, request)).toEqual({
        valid: false,
        catalog_schema_version: 1,
        request_generation: null,
        typed_prefix: null,
        suggestions: [],
      })
    }
  })

  it('requires both exact input and generation to accept a projection as current', () => {
    const projected = projectCommandSuggestions(
      catalog(catalogEntry('now', 'Playback')),
      { typedPrefix: 'n', generation: 12 },
    )

    expect(isCommandSuggestionProjectionCurrent(projected, 'n', 12)).toBe(true)
    expect(isCommandSuggestionProjectionCurrent(projected, 'no', 12)).toBe(false)
    expect(isCommandSuggestionProjectionCurrent(projected, 'N', 12)).toBe(false)
    expect(isCommandSuggestionProjectionCurrent(projected, 'n', 13)).toBe(false)
    expect(isCommandSuggestionProjectionCurrent(projected, 'n\n', 12)).toBe(false)
  })
})
