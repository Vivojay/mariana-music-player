import type { ITheme } from '@xterm/xterm'

export type ThemeName = 'aurora' | 'windows' | 'kitty' | 'gruvbox'

export type MarianaTheme = {
  name: string
  terminal: ITheme
  chrome: { background: string; panel: string; border: string; accent: string; text: string; muted: string; glow: string }
}

export const themes: Record<ThemeName, MarianaTheme> = {
  aurora: {
    name: 'Mariana Aurora',
    terminal: {
      background: '#090c18', foreground: '#dce5ff', cursor: '#6cf5d2', cursorAccent: '#090c18',
      selectionBackground: '#6a5cff55', black: '#101423', red: '#ff6f91', green: '#6cf5aa', yellow: '#ffd479',
      blue: '#67b7ff', magenta: '#c89bff', cyan: '#61e7ef', white: '#eaf0ff', brightBlack: '#65708d',
      brightRed: '#ff94aa', brightGreen: '#91ffbf', brightYellow: '#ffe2a1', brightBlue: '#91cdff',
      brightMagenta: '#ddbaff', brightCyan: '#9bf5f8', brightWhite: '#ffffff',
    },
    chrome: { background: '#060811', panel: '#101528cc', border: '#7785b32d', accent: '#6cf5d2', text: '#e8eeff', muted: '#8c98b8', glow: '#715cff' },
  },
  windows: {
    name: 'Windows Terminal Acrylic',
    terminal: {
      background: '#0c0c0cd9', foreground: '#f2f2f2', cursor: '#f2f2f2', selectionBackground: '#ffffff3d',
      black: '#0c0c0c', red: '#c50f1f', green: '#13a10e', yellow: '#c19c00', blue: '#0037da', magenta: '#881798',
      cyan: '#3a96dd', white: '#cccccc', brightBlack: '#767676', brightRed: '#e74856', brightGreen: '#16c60c',
      brightYellow: '#f9f1a5', brightBlue: '#3b78ff', brightMagenta: '#b4009e', brightCyan: '#61d6d6', brightWhite: '#f2f2f2',
    },
    chrome: { background: '#080808', panel: '#1b1b1bd9', border: '#ffffff1f', accent: '#60cdff', text: '#f4f4f4', muted: '#a0a0a0', glow: '#0078d4' },
  },
  kitty: {
    name: 'Kitty / Catppuccin',
    terminal: {
      background: '#1e1e2e', foreground: '#cdd6f4', cursor: '#f5e0dc', selectionBackground: '#585b70aa',
      black: '#45475a', red: '#f38ba8', green: '#a6e3a1', yellow: '#f9e2af', blue: '#89b4fa', magenta: '#f5c2e7',
      cyan: '#94e2d5', white: '#bac2de', brightBlack: '#585b70', brightRed: '#f38ba8', brightGreen: '#a6e3a1',
      brightYellow: '#f9e2af', brightBlue: '#89b4fa', brightMagenta: '#f5c2e7', brightCyan: '#94e2d5', brightWhite: '#a6adc8',
    },
    chrome: { background: '#11111b', panel: '#181825e6', border: '#cba6f733', accent: '#cba6f7', text: '#cdd6f4', muted: '#7f849c', glow: '#89b4fa' },
  },
  gruvbox: {
    name: 'Gruvbox Dark',
    terminal: {
      background: '#282828', foreground: '#ebdbb2', cursor: '#fabd2f', selectionBackground: '#665c54aa',
      black: '#282828', red: '#cc241d', green: '#98971a', yellow: '#d79921', blue: '#458588', magenta: '#b16286',
      cyan: '#689d6a', white: '#a89984', brightBlack: '#928374', brightRed: '#fb4934', brightGreen: '#b8bb26',
      brightYellow: '#fabd2f', brightBlue: '#83a598', brightMagenta: '#d3869b', brightCyan: '#8ec07c', brightWhite: '#ebdbb2',
    },
    chrome: { background: '#1d2021', panel: '#282828e8', border: '#fabd2f2b', accent: '#fabd2f', text: '#ebdbb2', muted: '#a89984', glow: '#b8bb26' },
  },
}
