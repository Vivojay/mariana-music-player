import { describe, expect, it } from 'vitest'
import { projectCommandCatalog, validateCommandCatalogOptions } from './commandCatalog'

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
