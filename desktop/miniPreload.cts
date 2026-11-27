import { contextBridge, ipcRenderer } from 'electron'
import type { MarianaMiniPlayerApi, MiniPlayerSnapshot } from './shared.js'

const api: MarianaMiniPlayerApi = {
  videoStatus: () => ipcRenderer.invoke('mini:video-status'),
  videoConfigure: (mediaId, mode) => ipcRenderer.invoke('mini:video-configure', mediaId, mode),
  videoFilter: (mediaId, preset, threshold) => ipcRenderer.invoke('mini:video-filter', mediaId, preset, threshold),
  videoCaptionFile: (mediaId, replace) => ipcRenderer.invoke('mini:video-caption-file', mediaId, replace),
  videoCaptionSelect: (mediaId, revision, trackId) => ipcRenderer.invoke('mini:video-caption-select', mediaId, revision, trackId),
  videoCaptionLanguages: (mediaId, languages) => ipcRenderer.invoke('mini:video-caption-languages', mediaId, languages),
  videoCaptionAutomatic: (mediaId) => ipcRenderer.invoke('mini:video-caption-automatic', mediaId),
  videoCaptionConfigure: (mediaId, action, value) => ipcRenderer.invoke('mini:video-caption-configure', mediaId, action, value),
  videoAudioOffset: (mediaId, value, relative) => ipcRenderer.invoke('mini:video-audio-offset', mediaId, value, relative),
  downloadCurrent: (mediaId, format) => ipcRenderer.invoke('mini:download-current', mediaId, format),
  downloadStatus: () => ipcRenderer.invoke('mini:download-status'),
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
  seek: (mediaId, targetSeconds) => ipcRenderer.invoke('mini:seek', mediaId, targetSeconds),
  showMain: () => ipcRenderer.invoke('mini:show-main'),
  hide: () => ipcRenderer.invoke('mini:hide'),
  platform: process.platform,
}

contextBridge.exposeInMainWorld('marianaMini', api)
