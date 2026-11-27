import { expect, it } from 'vitest'
import { exploreCommandSuggestions } from './commandExplorer'
import type { CommandCatalogSnapshot } from './shared'

function snapshot(canonical: string): CommandCatalogSnapshot {
  return { schema_version: 1, entries: [{ key: canonical, canonical, category: 'Music',
    summary: 'Catalog entry', risk: 'read-only', aliases: [], availability: [], forms: [] }] }
}

it('retains native grammar-only aliases alongside original catalog results', () => {
  const results = exploreCommandSuggestions(snapshot('input-monitor'), { typedPrefix: 'in', generation: 1 }).suggestions
  expect(results.map(row => row.display_label)).toEqual(expect.arrayContaining(['in', 'include', 'input-monitor']))
  const alias = results.find(row => row.display_label === 'in')
  expect(alias?.risk).toBe('unspecified')
  expect(alias).not.toHaveProperty('action')
})

it('combines catalog and grammar branches under an existing prefix and offers scoped typos', () => {
  const results = exploreCommandSuggestions(snapshot('dj crate'), { typedPrefix: 'dj c', generation: 2 }).suggestions
  expect(results.map(row => row.display_label)).toEqual(expect.arrayContaining(['dj crate', 'dj crossfade', 'dj cue']))
  const repairs = exploreCommandSuggestions(snapshot('jam'), { typedPrefix: 'jam cuue', generation: 3 }).suggestions
  expect(repairs[0]).toMatchObject({ display_label: 'jam cue', match_kind: 'correction' })
  expect(repairs[0]).not.toHaveProperty('insertion_text')
})
