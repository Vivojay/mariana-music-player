import { contextBridge, ipcRenderer } from 'electron'

type RenderRequest = {
  requestId: string
  code: string
  previewSeconds: number
}

contextBridge.exposeInMainWorld('strudelHost', {
  onRender(callback: (request: RenderRequest) => void) {
    const listener = (_event: Electron.IpcRendererEvent, request: RenderRequest) => callback(request)
    ipcRenderer.on('strudel:render', listener)
    return () => ipcRenderer.removeListener('strudel:render', listener)
  },
  complete(requestId: string, bytes: ArrayBuffer) {
    ipcRenderer.send('strudel:complete', requestId, bytes)
  },
  fail(requestId: string, message: string) {
    ipcRenderer.send('strudel:failed', requestId, message)
  },
})
