import type { MarianaDesktopApi } from './shared'

declare module '@fontsource-variable/cascadia-code'

declare global {
  interface Window {
    mariana: MarianaDesktopApi
  }
}

export {}
