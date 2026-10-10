import type { MarianaDesktopApi, MarianaMiniPlayerApi } from './shared'

declare module '@fontsource-variable/cascadia-code'

declare global {
  interface Window {
    mariana: MarianaDesktopApi
    marianaMini: MarianaMiniPlayerApi
    strudelHost: {
      onRender(callback: (request: { requestId: string; code: string; previewSeconds: number }) => void): () => void
      complete(requestId: string, bytes: ArrayBuffer): void
      fail(requestId: string, message: string): void
    }
  }
}

export {}
