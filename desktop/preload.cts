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
    discoveryBegin: (itemId, requestId, page) => ipcRenderer.invoke('backend:discovery-begin', itemId, requestId, page),
    discoveryChoose: (requestId, revision, choiceId, intent) => ipcRenderer.invoke('backend:discovery-choose', requestId, revision, choiceId, intent),
    discoveryCancel: (requestId) => ipcRenderer.invoke('backend:discovery-cancel', requestId),
    homepageRefresh: () => ipcRenderer.invoke('backend:homepage-refresh'),
    homepageOpen: () => ipcRenderer.invoke('backend:homepage-open'),
    homepageConfigure: (setting, enabled) => ipcRenderer.invoke('backend:homepage-configure', setting, enabled),
    homepageImageData: (cacheKey) => ipcRenderer.invoke('backend:homepage-image-data', cacheKey),
    focusRecoveryRetry: () => ipcRenderer.invoke('backend:focus-recovery-retry'),
    lyricsStatus: () => ipcRenderer.invoke('backend:lyrics-status'),
    lyricsRequest: (mediaId, refresh) => ipcRenderer.invoke('backend:lyrics-request', mediaId, refresh),
    lyricsOffset: (mediaId, offsetMs) => ipcRenderer.invoke('backend:lyrics-offset', mediaId, offsetMs),
    lyricsHide: () => ipcRenderer.invoke('backend:lyrics-hide'),
    artworkConfigure: (enabled) => ipcRenderer.invoke('backend:artwork-configure', enabled),
    artworkShow: (mediaId, fetch) => ipcRenderer.invoke('backend:artwork-show', mediaId, fetch),
    artworkData: (cacheKey) => ipcRenderer.invoke('backend:artwork-data', cacheKey),
    crossfadeConfigure: (seconds) => ipcRenderer.invoke('backend:crossfade-configure', seconds),
    strudelOpen: () => ipcRenderer.invoke('backend:strudel-open'),
    strudelSave: (input) => ipcRenderer.invoke('backend:strudel-save', input),
    strudelDelete: (projectId, revision) => ipcRenderer.invoke('backend:strudel-delete', projectId, revision),
    strudelPreview: (input) => ipcRenderer.invoke('backend:strudel-preview', input),
    seek: (mediaId, targetSeconds) => ipcRenderer.invoke('backend:seek', mediaId, targetSeconds),
    play: (mediaId) => ipcRenderer.invoke('backend:play', mediaId),
    pause: (mediaId) => ipcRenderer.invoke('backend:pause', mediaId),
    previous: (mediaId) => ipcRenderer.invoke('backend:previous', mediaId),
    next: (mediaId) => ipcRenderer.invoke('backend:next', mediaId),
    videoStatus: () => ipcRenderer.invoke('backend:video-status'),
    downloadCurrent: (mediaId, format) => ipcRenderer.invoke('backend:download-current', mediaId, format),
    downloadStatus: () => ipcRenderer.invoke('backend:download-status'),
    videoConfigure: (mediaId, mode) => ipcRenderer.invoke('backend:video-configure', mediaId, mode),
    videoCaptionFile: (mediaId, replace) => ipcRenderer.invoke('backend:video-caption-file', mediaId, replace),
    videoCaptionSelect: (mediaId, revision, trackId) => ipcRenderer.invoke('backend:video-caption-select', mediaId, revision, trackId),
    videoCaptionLanguages: (mediaId, languages) => ipcRenderer.invoke('backend:video-caption-languages', mediaId, languages),
    videoCaptionAutomatic: (mediaId) => ipcRenderer.invoke('backend:video-caption-automatic', mediaId),
    videoCaptionConfigure: (mediaId, action, value) => ipcRenderer.invoke('backend:video-caption-configure', mediaId, action, value),
    videoAudioOffset: (mediaId, value, relative) => ipcRenderer.invoke('backend:video-audio-offset', mediaId, value, relative),
    videoWindow: (open) => ipcRenderer.invoke('backend:video-window', open),
    equalizerStatus: () => ipcRenderer.invoke('backend:equalizer-status'),
    equalizerConfigure: (intent) => ipcRenderer.invoke('backend:equalizer-configure', intent),
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
