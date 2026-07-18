import { contextBridge, ipcRenderer } from 'electron'
import type { MarianaMiniPlayerApi, MiniPlayerSnapshot } from './shared.js'

const api: MarianaMiniPlayerApi = {
  snapshot: () => ipcRenderer.invoke('mini:snapshot'),
  onSnapshot: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, snapshot: MiniPlayerSnapshot) => callback(snapshot)
    ipcRenderer.on('mini:snapshot-updated', listener)
    return () => ipcRenderer.removeListener('mini:snapshot-updated', listener)
  },
  showMain: () => ipcRenderer.invoke('mini:show-main'),
  hide: () => ipcRenderer.invoke('mini:hide'),
  platform: process.platform,
}

contextBridge.exposeInMainWorld('marianaMini', api)
