import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { PaletteEditor } from './PaletteEditor'
import { readSelection, resolveTheme, selection, themes } from './themes'

it('limits saved colors to known tokens, including correctly cased xterm names', () => {
  const palette = selection('redblood', { 'terminal.brightRed': '#ffeedd', 'chrome.accent': 'url(no)', 'other.x': '#ffffff' })
  expect(palette.colors).toEqual({ 'terminal.brightRed': '#ffeedd' })
  expect(resolveTheme(palette).terminal.brightRed).toBe('#ffeedd')
  expect(themes.redblood.terminal.brightRed).not.toBe('#ffeedd')
  localStorage.setItem('mariana.theme', 'redblood')
  localStorage.setItem('mariana.themeColors', '{')
  expect(readSelection()).toEqual(selection('redblood'))
  localStorage.clear()
})

it('edits a selected token and restores the current preset', () => {
  const save = vi.fn()
  const reset = vi.fn()
  render(<PaletteEditor theme={themes.dracula} onSave={save} onReset={reset} />)
  fireEvent.click(screen.getByRole('button', { name: 'Colors' }))
  fireEvent.change(screen.getByLabelText('Theme color'), { target: { value: 'terminal.cursor' } })
  fireEvent.change(screen.getByLabelText('Hex color'), { target: { value: '#aabbcc77' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply color' }))
  expect(save).toHaveBeenCalledWith('terminal.cursor', '#aabbcc77')
  fireEvent.change(screen.getByLabelText('Hex color'), { target: { value: 'invalid' } })
  expect(screen.getByRole('button', { name: 'Apply color' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Reset this preset' }))
  expect(reset).toHaveBeenCalledOnce()
})
