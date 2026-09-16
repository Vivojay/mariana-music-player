import { contextBridge, ipcRenderer } from 'electron'
import type { BackendEvent, MarianaDesktopApi, TerminalExit, UpdateState } from './shared.js'

const subscribe = <T,>(channel: string, callback: (value: T) => void) => {
  const listener = (_event: Electron.IpcRendererEvent, value: T) => callback(value)
  ipcRenderer.on(channel, listener)
  return () => ipcRenderer.removeListener(channel, listener)
}

const api: MarianaDesktopApi = {
  terminal: {
    write: (data) => ipcRenderer.send('terminal:write', data),
    resize: (cols, rows) => ipcRenderer.send('terminal:resize', { cols, rows }),
    restart: () => ipcRenderer.invoke('terminal:restart'),
    history: () => ipcRenderer.invoke('terminal:history'),
    onData: (callback) => subscribe<string>('terminal:data', callback),
    onExit: (callback) => subscribe<TerminalExit>('terminal:exit', callback),
  },
  backend: {
    snapshot: () => ipcRenderer.invoke('backend:snapshot'),
    commandCatalog: (options) => ipcRenderer.invoke('backend:command-catalog', options),
    toggleFavorite: (mediaId) => ipcRenderer.invoke('backend:favorite-toggle', mediaId),
    setRating: (mediaId, rating) => ipcRenderer.invoke('backend:rating-set', mediaId, rating),
    seek: (mediaId, targetSeconds) => ipcRenderer.invoke('backend:seek', mediaId, targetSeconds),
    play: (mediaId) => ipcRenderer.invoke('backend:play', mediaId),
    pause: (mediaId) => ipcRenderer.invoke('backend:pause', mediaId),
    previous: (mediaId) => ipcRenderer.invoke('backend:previous', mediaId),
    next: (mediaId) => ipcRenderer.invoke('backend:next', mediaId),
    videoStatus: () => ipcRenderer.invoke('backend:video-status'),
    videoConfigure: (mediaId, mode) => ipcRenderer.invoke('backend:video-configure', mediaId, mode),
    videoCaptionFile: (mediaId, replace) => ipcRenderer.invoke('backend:video-caption-file', mediaId, replace),
    videoCaptionSelect: (mediaId, revision, trackId) => ipcRenderer.invoke('backend:video-caption-select', mediaId, revision, trackId),
    videoCaptionLanguages: (mediaId, languages) => ipcRenderer.invoke('backend:video-caption-languages', mediaId, languages),
    videoCaptionAutomatic: (mediaId) => ipcRenderer.invoke('backend:video-caption-automatic', mediaId),
    videoCaptionConfigure: (mediaId, action, value) => ipcRenderer.invoke('backend:video-caption-configure', mediaId, action, value),
    videoAudioOffset: (mediaId, value, relative) => ipcRenderer.invoke('backend:video-audio-offset', mediaId, value, relative),
    onEvent: (callback) => subscribe<BackendEvent>('backend:event', callback),
  },
  updates: {
    check: () => ipcRenderer.invoke('updates:check'),
    install: () => ipcRenderer.invoke('updates:install'),
    onState: (callback) => subscribe<UpdateState>('updates:state', callback),
  },
  clipboard: {
    writeText: (value) => ipcRenderer.invoke('clipboard:write-text', value),
  },
  app: {
    close: () => ipcRenderer.invoke('app:close'),
    showMiniPlayer: () => ipcRenderer.invoke('app:show-mini-player'),
  },
  openExternal: (url) => ipcRenderer.invoke('shell:open-external', url),
  platform: process.platform,
}

contextBridge.exposeInMainWorld('mariana', api)
