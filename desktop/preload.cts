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
    toggleFavorite: (mediaId) => ipcRenderer.invoke('backend:favorite-toggle', mediaId),
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
  },
  openExternal: (url) => ipcRenderer.invoke('shell:open-external', url),
  platform: process.platform,
}

contextBridge.exposeInMainWorld('mariana', api)
