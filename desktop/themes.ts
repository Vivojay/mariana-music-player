import type { CSSProperties } from 'react'
import type { ITheme } from '@xterm/xterm'
import presets from '../mariana/theme_presets.json'

export type ThemeName = keyof typeof presets
export type MarianaTheme = {
  name: string
  terminal: ITheme
  chrome: typeof presets.aurora.chrome
}
export const themes: Record<ThemeName, MarianaTheme> = presets
export const validColor = /^#[0-9a-f]{6}(?:[0-9a-f]{2})?$/i
export type ThemeSelection = { name: ThemeName; colors: Record<string, string> }

export function isThemeName(value: unknown): value is ThemeName {
  return typeof value === 'string' && Object.hasOwn(themes, value)
}

export function selection(name: ThemeName, value?: unknown): ThemeSelection {
  const colors: Record<string, string> = {}
  if (value && typeof value === 'object') {
    for (const group of ['chrome', 'terminal'] as const) {
      for (const token of Object.keys(themes[name][group])) {
        const key = `${group}.${token}`
        const color = (value as Record<string, unknown>)[key]
        if (typeof color === 'string' && validColor.test(color)) colors[key] = color
      }
    }
  }
  return { name, colors }
}

export function readSelection(): ThemeSelection {
  const name = localStorage.getItem('mariana.theme')
  if (!isThemeName(name)) return selection('aurora')
  try {
    const cache = JSON.parse(localStorage.getItem('mariana.themeColors') ?? 'null')
    return selection(name, cache?.name === name ? cache.colors : undefined)
  } catch {
    return selection(name)
  }
}

export function resolveTheme({ name, colors }: ThemeSelection): MarianaTheme {
  const preset = themes[name]
  const result = { ...preset, chrome: { ...preset.chrome }, terminal: { ...preset.terminal } }
  for (const group of ['chrome', 'terminal'] as const) {
    const tokens = result[group] as Record<string, string>
    for (const token of Object.keys(tokens)) {
      const color = colors[`${group}.${token}`]
      if (color) tokens[token] = color
    }
  }
  return result
}

export function themeStyle(theme: MarianaTheme): CSSProperties {
  return Object.fromEntries(Object.entries(theme.chrome).map(([key, value]) => [
    key === 'background' ? '--app-bg' : '--' + key, value,
  ])) as CSSProperties
}
