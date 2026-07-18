import type { MarianaDesktopApi, MarianaMiniPlayerApi } from './shared'

declare module '@fontsource-variable/cascadia-code'

declare global {
  interface Window {
    mariana: MarianaDesktopApi
    marianaMini: MarianaMiniPlayerApi
  }
}

export {}
