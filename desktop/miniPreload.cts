import { contextBridge, ipcRenderer } from 'electron'
import type { MarianaMiniPlayerApi, MiniPlayerSnapshot } from './shared.js'

const api: MarianaMiniPlayerApi = {
  videoStatus: () => ipcRenderer.invoke('mini:video-status'),
  videoCaptionConfigure: (mediaId, action, value) => ipcRenderer.invoke('mini:video-caption-configure', mediaId, action, value),
  videoAudioOffset: (mediaId, value, relative) => ipcRenderer.invoke('mini:video-audio-offset', mediaId, value, relative),
  snapshot: () => ipcRenderer.invoke('mini:snapshot'),
  onSnapshot: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, snapshot: MiniPlayerSnapshot) => callback(snapshot)
    ipcRenderer.on('mini:snapshot-updated', listener)
    return () => ipcRenderer.removeListener('mini:snapshot-updated', listener)
  },
  play: (mediaId) => ipcRenderer.invoke('mini:play', mediaId),
  pause: (mediaId) => ipcRenderer.invoke('mini:pause', mediaId),
  previous: (mediaId) => ipcRenderer.invoke('mini:previous', mediaId),
  next: (mediaId) => ipcRenderer.invoke('mini:next', mediaId),
  showMain: () => ipcRenderer.invoke('mini:show-main'),
  hide: () => ipcRenderer.invoke('mini:hide'),
  platform: process.platform,
}

contextBridge.exposeInMainWorld('marianaMini', api)
