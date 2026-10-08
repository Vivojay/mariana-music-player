import { afterEach, expect, it, vi } from 'vitest'
import { readChapterSnapping, saveChapterSnapping, SNAP_CHAPTERS_KEY } from './seekPreferences'

afterEach(() => { vi.restoreAllMocks(); localStorage.clear() })

it('defaults off, persists explicit choices, and ignores invalid stored values', () => {
  expect(readChapterSnapping()).toBe(false)
  expect(saveChapterSnapping(true)).toBe(true)
  expect(readChapterSnapping()).toBe(true)
  expect(saveChapterSnapping(false)).toBe(true)
  expect(readChapterSnapping()).toBe(false)
  localStorage.setItem(SNAP_CHAPTERS_KEY, 'yes')
  expect(readChapterSnapping()).toBe(false)
})

it('fails safely when preference storage is unavailable', () => {
  vi.spyOn(localStorage, 'getItem').mockImplementation(() => { throw new Error('Unavailable') })
  vi.spyOn(localStorage, 'setItem').mockImplementation(() => { throw new Error('Unavailable') })
  expect(readChapterSnapping()).toBe(false)
  expect(saveChapterSnapping(true)).toBe(false)
})
