import { app, BrowserWindow, clipboard, ipcMain, Menu, nativeImage, shell, Tray } from 'electron'
import electronUpdater from 'electron-updater'
import { randomBytes } from 'node:crypto'
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import * as pty from 'node-pty'
import { projectCommandCatalog, validateCommandCatalogOptions } from './commandCatalog.js'
import { acceptPlaybackStatusEvent } from './playbackProjection.js'
import { validateSeekIntent } from './playbackSeek.js'
import type {
  BackendEvent,
  CommandCatalogOptions,
  CommandCatalogResult,
  DesktopControlResult,
  MiniPlayerSnapshot,
  PlaybackStatus,
  UpdateState,
} from './shared.js'
import {
  createTrayActions,
  ensureSingleWindow,
  ensureSingleTray,
  handleAuxiliaryWindowClose,
  handleWindowClose,
  normalizeCloseButtonBehavior,
  showWindow,
  type CloseButtonBehavior,
} from './windowLifecycle.js'

const { autoUpdater } = electronUpdater

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repositoryRoot = path.resolve(__dirname, '..')
const isDevelopment = !app.isPackaged
const usesViteRenderer = isDevelopment && process.env.MARIANA_E2E_USE_DIST !== '1'
if (process.env.MARIANA_E2E === '1') {
  app.setPath(
    'userData',
    process.env.MARIANA_E2E_DATA_DIR || path.join(app.getPath('temp'), `mariana-e2e-${process.pid}`),
  )
}
const controlToken = randomBytes(32).toString('hex')
const controlEndpoint = process.platform === 'win32'
  ? `\\\\.\\pipe\\mariana-${process.pid}-${randomBytes(8).toString('hex')}`
  : path.join(app.getPath('temp'), `mariana-${process.pid}-${randomBytes(8).toString('hex')}.sock`)

let mainWindow: BrowserWindow | null = null
let miniPlayerWindow: BrowserWindow | null = null
let terminalProcess: pty.IPty | null = null
let controlServer: net.Server | null = null
let controlSocket: net.Socket | null = null
let tray: Tray | null = null
let trayAvailable = false
let closeButtonBehavior: CloseButtonBehavior = 'tray'
let desktopNotice: string | null = null
let terminalHistory = ''
let terminalControlTail = ''
let quitting = false
let playbackState = 'idle'
let playbackStatus: PlaybackStatus | null = null
let playbackEventTimestamp: number | null = null
let sleepActive = false
let backendReady = false
let backendShutdownAcknowledged = false
let backendExitClosesView = true
let backendSafeOverride: boolean | null = null
let backendDiagnostic: string | null = null
let updateState: UpdateState = { state: app.isPackaged ? 'idle' : 'disabled' }
let updatePreparationTimer: NodeJS.Timeout | null = null
let backendStartupTimer: NodeJS.Timeout | null = null
const pendingControlRequests = new Map<string, {
  resolve: (result: DesktopControlResult) => void
  timer: NodeJS.Timeout
  safeError: string
  interrupted: string
}>()
const pendingCommandCatalogRequests = new Map<string, {
  resolve: (result: CommandCatalogResult) => void
  timer: NodeJS.Timeout
}>()

type ControlRequestMessages = {
  timeout: string
  send: string
  safeError: string
  interrupted: string
}

const favoriteControlMessages: ControlRequestMessages = {
  timeout: 'Mariana backend did not confirm the favourite update',
  send: 'Could not send the favourite update',
  safeError: 'Favourite update failed',
  interrupted: 'Mariana backend interrupted the favourite update',
}

const playbackControlMessages: ControlRequestMessages = {
  timeout: 'Mariana backend did not confirm the playback control',
  send: 'Could not send the playback control',
  safeError: 'Playback control failed',
  interrupted: 'Mariana backend interrupted the playback control',
}

const seekControlMessages: ControlRequestMessages = {
  timeout: 'Mariana backend did not confirm the seek',
  send: 'Could not send the seek',
  safeError: 'Seek failed',
  interrupted: 'Mariana backend interrupted the seek',
}

const safeToInstall = () => (
  backendSafeOverride ?? (['idle', 'paused', 'failed'].includes(playbackState) && !sleepActive)
)

const send = <T>(channel: string, value: T) => {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send(channel, value)
}

const miniPlayerSnapshot = (): MiniPlayerSnapshot => ({
  ready: backendReady,
  diagnostic: backendDiagnostic,
  playback: playbackStatus,
})

const sendMiniPlayerSnapshot = () => {
  if (miniPlayerWindow && !miniPlayerWindow.isDestroyed()) {
    miniPlayerWindow.webContents.send('mini:snapshot-updated', miniPlayerSnapshot())
  }
}

const trayActions = createTrayActions(
  () => mainWindow,
  () => {
    quitting = true
    app.quit()
  },
)

function setDesktopNotice(message: string | null) {
  desktopNotice = message
  if (message) {
    send('backend:event', {
      event: 'desktop-notice',
      payload: { message },
      timestamp: Date.now() / 1000,
    } satisfies BackendEvent)
  }
}

function ensureTray(): boolean {
  if (tray) return true
  try {
    const iconPath = isDevelopment
      ? path.join(repositoryRoot, 'res', 'welcome_banner.png')
      : path.join(process.resourcesPath, 'tray-icon.png')
    const source = nativeImage.createFromPath(iconPath)
    if (source.isEmpty()) throw new Error('tray icon unavailable')
    const size = process.platform === 'darwin' ? 18 : process.platform === 'win32' ? 16 : 22
    tray = ensureSingleTray(tray, () => new Tray(source.resize({ width: size, height: size })))
    tray.setToolTip('Mariana')
    tray.setContextMenu(Menu.buildFromTemplate([
      { label: 'Show Mariana', click: trayActions.show },
      { label: 'Hide Mariana', click: trayActions.hide },
      { type: 'separator' },
      { label: 'Quit', click: trayActions.quit },
    ]))
    tray.on('double-click', trayActions.show)
    trayAvailable = true
    setDesktopNotice(null)
    return true
  } catch {
    trayAvailable = false
    setDesktopNotice('System tray is unavailable; the close button will quit Mariana')
    return false
  }
}

const setUpdateState = (next: UpdateState) => {
  updateState = { ...next, safeToInstall: safeToInstall() }
  send('updates:state', updateState)
}

function validateSender(event: Electron.IpcMainEvent | Electron.IpcMainInvokeEvent): boolean {
  return Boolean(mainWindow && event.sender === mainWindow.webContents)
}

function validateMiniPlayerSender(event: Electron.IpcMainInvokeEvent): boolean {
  return Boolean(miniPlayerWindow && event.sender === miniPlayerWindow.webContents)
}

function validControlMediaId(value: unknown): value is string {
  return typeof value === 'string'
    && value.length > 0
    && value.length <= 256
    && !Array.from(value).some((character) => {
      const code = character.charCodeAt(0)
      return code < 32 || code === 127
    })
}

function safeControlError(value: unknown, fallback = favoriteControlMessages.safeError): string {
  const text = typeof value === 'string'
    ? Array.from(value, (character) => {
        const code = character.charCodeAt(0)
        return code < 32 || code === 127 ? ' ' : character
      }).join('').replace(/\s+/g, ' ').trim()
    : ''
  if (!text || /(?:https?:\/\/|[a-z]:[\\/]|\\\\|\b(?:cookie|token|secret|authorization)\b)/i.test(text)) {
    return fallback
  }
  return text.slice(0, 160)
}

function finishPendingControlRequests() {
  for (const { resolve, timer, interrupted } of pendingControlRequests.values()) {
    clearTimeout(timer)
    resolve({ ok: false, error: interrupted })
  }
  pendingControlRequests.clear()
  for (const { resolve, timer } of pendingCommandCatalogRequests.values()) {
    clearTimeout(timer)
    resolve({ ok: false, error: 'Mariana backend interrupted the command catalog request' })
  }
  pendingCommandCatalogRequests.clear()
}

function requestCommandCatalog(options: CommandCatalogOptions): Promise<CommandCatalogResult> {
  const socket = controlSocket
  if (!backendReady || !socket || socket.destroyed || !socket.writable) {
    return Promise.resolve({ ok: false, error: 'Mariana backend is unavailable' })
  }
  const requestId = randomBytes(16).toString('hex')
  const payload = {
    ...(options.includeCompatibility === undefined
      ? {}
      : { include_compatibility: options.includeCompatibility }),
    ...(options.typedPrefix === undefined ? {} : { typed_prefix: options.typedPrefix }),
  }
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      pendingCommandCatalogRequests.delete(requestId)
      resolve({ ok: false, error: 'Mariana backend did not return the command catalog' })
    }, 3_000)
    pendingCommandCatalogRequests.set(requestId, { resolve, timer })
    socket.write(`${JSON.stringify({
      token: controlToken,
      request_id: requestId,
      action: 'autocomplete.catalog',
      payload,
    })}\n`, (error) => {
      if (!error) return
      const pending = pendingCommandCatalogRequests.get(requestId)
      if (!pending) return
      clearTimeout(pending.timer)
      pendingCommandCatalogRequests.delete(requestId)
      pending.resolve({ ok: false, error: 'Could not request the command catalog' })
    })
  })
}

function requestBackendControl(
  action: string,
  payload: Record<string, unknown>,
  messages = favoriteControlMessages,
): Promise<DesktopControlResult> {
  const socket = controlSocket
  if (!backendReady || !socket || socket.destroyed || !socket.writable) {
    return Promise.resolve({ ok: false, error: 'Mariana backend is unavailable' })
  }
  const requestId = randomBytes(16).toString('hex')
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      pendingControlRequests.delete(requestId)
      resolve({ ok: false, error: messages.timeout })
    }, 3_000)
    pendingControlRequests.set(requestId, {
      resolve,
      timer,
      safeError: messages.safeError,
      interrupted: messages.interrupted,
    })
    socket.write(`${JSON.stringify({ token: controlToken, request_id: requestId, action, payload })}\n`, (error) => {
      if (!error) return
      const pending = pendingControlRequests.get(requestId)
      if (!pending) return
      clearTimeout(pending.timer)
      pendingControlRequests.delete(requestId)
      pending.resolve({ ok: false, error: messages.send })
    })
  })
}

function handleBackendEvent(event: BackendEvent) {
  let forwardedEvent = event
  if (event.event === 'playback') {
    const accepted = acceptPlaybackStatusEvent(
      event.payload,
      event.timestamp,
      playbackEventTimestamp,
    )
    if (!accepted) return
    playbackEventTimestamp = accepted.timestamp
    playbackState = accepted.status.state
    playbackStatus = accepted.status
    forwardedEvent = { ...event, payload: accepted.status }
  }
  if (event.event === 'sleep') sleepActive = Boolean(event.payload.active)
  if (event.event === 'update-safe') backendSafeOverride = Boolean(event.payload.safe)
  if (event.event === 'ready') {
    backendReady = true
    backendDiagnostic = null
    if (backendStartupTimer) clearTimeout(backendStartupTimer)
    backendStartupTimer = null
    fs.writeFileSync(path.join(app.getPath('userData'), 'healthy.json'), JSON.stringify({
      version: app.getVersion(), timestamp: Date.now(),
    }))
    closeButtonBehavior = normalizeCloseButtonBehavior(event.payload.close_button_behavior)
  }
  if (event.event === 'desktop-preferences') {
    closeButtonBehavior = normalizeCloseButtonBehavior(event.payload.close_button_behavior)
  }
  if (event.event === 'fatal-error' || event.event === 'shutdown-ack') backendReady = false
  if (event.event === 'fatal-error') trayActions.show()
  if (event.event === 'shutdown-ack') backendShutdownAcknowledged = true
  if (event.event === 'control-result') {
    const requestId = event.payload.request_id
    if (typeof requestId === 'string') {
      const catalogPending = pendingCommandCatalogRequests.get(requestId)
      if (catalogPending) {
        clearTimeout(catalogPending.timer)
        pendingCommandCatalogRequests.delete(requestId)
        const catalog = event.payload.ok === true
          ? projectCommandCatalog(event.payload.catalog)
          : null
        catalogPending.resolve(catalog ? { ok: true, catalog } : {
          ok: false,
          error: safeControlError(event.payload.error, 'Command catalog is unavailable'),
        })
      } else {
        const pending = pendingControlRequests.get(requestId)
        if (pending) {
          clearTimeout(pending.timer)
          pendingControlRequests.delete(requestId)
          const ok = event.payload.ok === true
          pending.resolve(ok ? { ok: true } : {
            ok: false,
            error: safeControlError(event.payload.error, pending.safeError),
          })
        }
      }
    }
  }
  if (event.event === 'update-prepared' && updateState.state === 'downloaded') {
    if (updatePreparationTimer) clearTimeout(updatePreparationTimer)
    quitting = true
    backendExitClosesView = false
    terminalProcess?.write('exit y\r')
    setTimeout(() => autoUpdater.quitAndInstall(false, true), 1200)
  }
  if (event.event !== 'control-result') send('backend:event', forwardedEvent)
  sendMiniPlayerSnapshot()
  if (updateState.state === 'downloaded') setUpdateState(updateState)
}

async function createControlServer(): Promise<void> {
  if (process.platform !== 'win32') fs.rmSync(controlEndpoint, { force: true })
  controlServer = net.createServer((socket) => {
    let pending = ''
    socket.setEncoding('utf8')
    socket.on('data', (chunk) => {
      pending += chunk
      const lines = pending.split('\n')
      pending = lines.pop() ?? ''
      for (const line of lines) {
        try {
          const message = JSON.parse(line) as (BackendEvent & { token?: string }) | {
            token?: string
            channel?: string
          }
          if (message.token !== controlToken) continue
          if ('channel' in message && message.channel === 'requests') {
            if (controlSocket && controlSocket !== socket) controlSocket.destroy()
            controlSocket = socket
            continue
          }
          if ('event' in message && typeof message.event === 'string') {
            handleBackendEvent(message)
          }
        } catch {
          // Ignore malformed local control messages without affecting the PTY.
        }
      }
    })
    socket.on('close', () => {
      if (controlSocket !== socket) return
      controlSocket = null
      finishPendingControlRequests()
    })
  })
  await new Promise<void>((resolve, reject) => {
    controlServer?.once('error', reject)
    controlServer?.listen(controlEndpoint, () => resolve())
  })
}

function backendCommand(): { executable: string; args: string[]; cwd: string; resources: string } {
  if (isDevelopment) {
    const virtualenvPython = process.platform === 'win32'
      ? path.join(repositoryRoot, '.venv', 'Scripts', 'python.exe')
      : path.join(repositoryRoot, '.venv', 'bin', 'python')
    const runnerRoot = process.env.pythonLocation || process.env.Python_ROOT_DIR
    const runnerPython = runnerRoot
      ? (process.platform === 'win32'
          ? path.join(runnerRoot, 'python.exe')
          : path.join(runnerRoot, 'bin', 'python'))
      : ''
    const executable = process.env.MARIANA_PYTHON
      || [virtualenvPython, runnerPython].find((candidate) => candidate && fs.existsSync(candidate))
      || 'python'
    return { executable, args: ['main.py'], cwd: repositoryRoot, resources: repositoryRoot }
  }
  const backend = path.join(process.resourcesPath, 'backend')
  const executable = path.join(backend, process.platform === 'win32' ? 'mariana-cli.exe' : 'mariana-cli')
  return { executable, args: [], cwd: backend, resources: backend }
}

function startTerminal() {
  terminalProcess?.kill()
  controlSocket?.destroy()
  controlSocket = null
  backendReady = false
  backendDiagnostic = null
  if (backendStartupTimer) clearTimeout(backendStartupTimer)
  send('backend:event', { event: 'starting', payload: {}, timestamp: Date.now() / 1000 } satisfies BackendEvent)
  finishPendingControlRequests()
  playbackState = 'idle'
  playbackStatus = null
  playbackEventTimestamp = null
  sendMiniPlayerSnapshot()
  backendShutdownAcknowledged = false
  backendExitClosesView = true
  const command = backendCommand()
  const spawnedProcess = pty.spawn(command.executable, command.args, {
    name: 'xterm-256color',
    cols: 120,
    rows: 34,
    cwd: command.cwd,
    env: {
      ...process.env,
      TERM: 'xterm-256color',
      COLORTERM: 'truecolor',
      MARIANA_DESKTOP: '1',
      MARIANA_RESOURCE_DIR: command.resources,
      MARIANA_DATA_DIR: path.join(app.getPath('userData'), 'runtime'),
      MARIANA_CONTROL_ENDPOINT: controlEndpoint,
      MARIANA_CONTROL_TOKEN: controlToken,
    },
  })
  terminalProcess = spawnedProcess
  backendStartupTimer = setTimeout(() => {
    if (terminalProcess !== spawnedProcess || backendReady) return
    backendDiagnostic = 'Backend control channel did not become ready'
    handleBackendEvent({
      event: 'fatal-error',
      payload: { message: backendDiagnostic },
      timestamp: Date.now() / 1000,
    })
  }, 30_000)
  spawnedProcess.onData((data) => {
    const controlWindow = terminalControlTail + data
    const clearIndex = Math.max(controlWindow.lastIndexOf('\u001b[2J'), controlWindow.lastIndexOf('\u001b[3J'))
    terminalHistory = clearIndex >= 0
      ? controlWindow.slice(clearIndex)
      : (terminalHistory + data).slice(-1_000_000)
    terminalControlTail = controlWindow.slice(-4)
    if (mainWindow && !mainWindow.webContents.isLoading()) send('terminal:data', data)
  })
  spawnedProcess.onExit(({ exitCode }) => {
    if (terminalProcess !== spawnedProcess) return
    terminalProcess = null
    if (backendStartupTimer) clearTimeout(backendStartupTimer)
    backendStartupTimer = null
    send('terminal:exit', {
      code: exitCode,
      intentional: backendShutdownAcknowledged && backendExitClosesView,
    })
  })
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 760,
    minHeight: 520,
    backgroundColor: '#080b16',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'hidden',
    titleBarOverlay: process.platform === 'darwin' ? false : {
      color: '#080b16', symbolColor: '#d9e2ff', height: 44,
    },
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  })
  if (process.env.MARIANA_E2E === '1') {
    mainWindow.webContents.on('console-message', (_event, level, message) => {
      console.log(`[renderer:${level}] ${message}`)
    })
    mainWindow.webContents.on('did-fail-load', (_event, code, description, url) => {
      console.error(`[renderer:load-failed] ${code} ${description} ${url}`)
    })
  }
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  mainWindow.webContents.on('will-navigate', (event, url) => {
    const allowed = usesViteRenderer
      ? new URL(url).origin === 'http://127.0.0.1:5173'
      : url.startsWith('file:') && fileURLToPath(url).startsWith(path.join(__dirname, '..', 'dist'))
    if (!allowed) event.preventDefault()
  })
  mainWindow.webContents.on('did-finish-load', () => {
    setUpdateState(updateState)
    if (desktopNotice) setDesktopNotice(desktopNotice)
  })
  if (usesViteRenderer) await mainWindow.loadURL('http://127.0.0.1:5173')
  else await mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
  mainWindow.on('close', (event) => {
    if (!mainWindow) return
    handleWindowClose(event, mainWindow, closeButtonBehavior, trayAvailable, quitting)
  })
  mainWindow.on('closed', () => {
    mainWindow = null
    if (!quitting) trayActions.quit()
  })
}

function configureRestrictedNavigation(window: BrowserWindow) {
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  window.webContents.on('will-navigate', (event, url) => {
    const allowed = usesViteRenderer
      ? new URL(url).origin === 'http://127.0.0.1:5173'
      : url.startsWith('file:') && fileURLToPath(url).startsWith(path.join(__dirname, '..', 'dist'))
    if (!allowed) event.preventDefault()
  })
}

async function ensureMiniPlayerWindow(): Promise<BrowserWindow> {
  let created = false
  const window = ensureSingleWindow(miniPlayerWindow, () => {
    created = true
    return new BrowserWindow({
      width: 400,
      height: 172,
      minWidth: 340,
      minHeight: 150,
      maxWidth: 600,
      maxHeight: 240,
      show: false,
      frame: false,
      resizable: true,
      skipTaskbar: false,
      alwaysOnTop: false,
      backgroundColor: '#15151d',
      title: 'Mariana Mini-player',
      webPreferences: {
        preload: path.join(__dirname, 'miniPreload.cjs'),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        webSecurity: true,
      },
    })
  })
  miniPlayerWindow = window
  if (!created) return window

  configureRestrictedNavigation(window)
  window.on('close', (event) => {
    handleAuxiliaryWindowClose(event, window, quitting)
  })
  window.on('closed', () => {
    if (miniPlayerWindow === window) miniPlayerWindow = null
  })
  if (usesViteRenderer) await window.loadURL('http://127.0.0.1:5173/?surface=mini')
  else await window.loadFile(path.join(__dirname, '..', 'dist', 'index.html'), { query: { surface: 'mini' } })
  return window
}

async function showMiniPlayer(): Promise<void> {
  const window = await ensureMiniPlayerWindow()
  if (!window.isDestroyed()) showWindow(window)
}

function registerIpc() {
  ipcMain.handle('backend:snapshot', async (event) => {
    if (!validateSender(event)) throw new Error('Invalid IPC sender')
    return {
      ready: backendReady,
      diagnostic: backendDiagnostic,
      desktopNotice,
      closeButtonBehavior,
      playbackState,
      sleepActive,
      playback: playbackStatus,
    }
  })
  ipcMain.handle('backend:command-catalog', async (event, rawOptions: unknown) => {
    if (!validateSender(event)) {
      return { ok: false, error: 'Command catalog request is invalid' } satisfies CommandCatalogResult
    }
    const options = validateCommandCatalogOptions(rawOptions)
    if (options === null) {
      return { ok: false, error: 'Command catalog request is invalid' } satisfies CommandCatalogResult
    }
    return requestCommandCatalog(options)
  })
  ipcMain.handle('backend:favorite-toggle', async (event, mediaId: unknown) => {
    if (!validateSender(event) || !validControlMediaId(mediaId)) {
      return { ok: false, error: 'Favourite target is unavailable' } satisfies DesktopControlResult
    }
    return requestBackendControl('favorite.toggle', { media_id: mediaId })
  })
  ipcMain.handle('backend:seek', async (event, mediaId: unknown, targetSeconds: unknown) => {
    if (!validateSender(event) || !validControlMediaId(mediaId)) {
      return { ok: false, error: 'Playback target is unavailable' } satisfies DesktopControlResult
    }
    const validation = validateSeekIntent(playbackStatus, mediaId, targetSeconds, backendReady)
    if (!validation.ok) return validation
    return requestBackendControl(
      'playback.seek',
      { media_id: mediaId, target_seconds: validation.targetSeconds },
      seekControlMessages,
    )
  })
  ipcMain.on('terminal:write', (event, data: unknown) => {
    if (validateSender(event) && typeof data === 'string' && data.length <= 1_000_000) terminalProcess?.write(data)
  })
  ipcMain.on('terminal:resize', (event, size: { cols?: unknown; rows?: unknown }) => {
    if (!validateSender(event)) return
    const cols = Number(size?.cols)
    const rows = Number(size?.rows)
    if (Number.isInteger(cols) && Number.isInteger(rows) && cols >= 20 && rows >= 5 && cols <= 500 && rows <= 200) {
      terminalProcess?.resize(cols, rows)
    }
  })
  ipcMain.handle('terminal:restart', async (event) => {
    if (!validateSender(event)) throw new Error('Invalid IPC sender')
    startTerminal()
  })
  ipcMain.handle('terminal:history', async (event) => {
    if (!validateSender(event)) throw new Error('Invalid IPC sender')
    return terminalHistory
  })
  ipcMain.handle('clipboard:write-text', async (event, value: unknown) => {
    if (!validateSender(event) || typeof value !== 'string' || value.length > 1_000_000) {
      throw new Error('Invalid clipboard text')
    }
    clipboard.writeText(value)
  })
  ipcMain.handle('app:close', async (event) => {
    if (!validateSender(event)) throw new Error('Invalid IPC sender')
    trayActions.quit()
  })
  ipcMain.handle('app:show-mini-player', async (event) => {
    if (!validateSender(event)) throw new Error('Invalid IPC sender')
    await showMiniPlayer()
  })
  ipcMain.handle('mini:snapshot', async (event) => {
    if (!validateMiniPlayerSender(event)) throw new Error('Invalid IPC sender')
    return miniPlayerSnapshot()
  })
  const miniPlaybackControl = (
    event: Electron.IpcMainInvokeEvent,
    mediaId: unknown,
    action: 'playback.play' | 'playback.pause' | 'playback.previous' | 'playback.next',
  ) => {
    if (!validateMiniPlayerSender(event) || !validControlMediaId(mediaId)) {
      return Promise.resolve({ ok: false, error: 'Playback target is unavailable' })
    }
    return requestBackendControl(action, { media_id: mediaId }, playbackControlMessages)
  }
  ipcMain.handle('mini:play', (event, mediaId) => miniPlaybackControl(event, mediaId, 'playback.play'))
  ipcMain.handle('mini:pause', (event, mediaId) => miniPlaybackControl(event, mediaId, 'playback.pause'))
  ipcMain.handle('mini:previous', (event, mediaId) => miniPlaybackControl(event, mediaId, 'playback.previous'))
  ipcMain.handle('mini:next', (event, mediaId) => miniPlaybackControl(event, mediaId, 'playback.next'))
  ipcMain.handle('mini:show-main', async (event) => {
    if (!validateMiniPlayerSender(event)) throw new Error('Invalid IPC sender')
    trayActions.show()
  })
  ipcMain.handle('mini:hide', async (event) => {
    if (!validateMiniPlayerSender(event)) throw new Error('Invalid IPC sender')
    miniPlayerWindow?.hide()
  })
  ipcMain.handle('shell:open-external', async (event, value: unknown) => {
    if (!validateSender(event) || typeof value !== 'string') throw new Error('Invalid external URL')
    const url = new URL(value)
    if (!['https:', 'http:'].includes(url.protocol)) throw new Error('Only HTTP(S) links are allowed')
    await shell.openExternal(url.toString())
  })
  ipcMain.handle('updates:check', async (event) => {
    if (!validateSender(event)) throw new Error('Invalid IPC sender')
    if (!app.isPackaged) return
    setUpdateState({ state: 'checking' })
    await autoUpdater.checkForUpdates()
  })
  ipcMain.handle('updates:install', async (event) => {
    if (!validateSender(event) || updateState.state !== 'downloaded' || !safeToInstall()) return false
    terminalProcess?.write('update prepare\r')
    updatePreparationTimer = setTimeout(() => {
      setUpdateState({ state: 'error', message: 'The backend did not confirm its update backup; installation was cancelled.' })
    }, 30_000)
    return true
  })
}

function configureUpdates() {
  if (!app.isPackaged) return
  autoUpdater.autoDownload = true
  autoUpdater.allowDowngrade = false
  autoUpdater.channel = 'latest'
  autoUpdater.on('checking-for-update', () => setUpdateState({ state: 'checking' }))
  autoUpdater.on('update-available', (info) => setUpdateState({ state: 'available', version: info.version }))
  autoUpdater.on('update-not-available', () => setUpdateState({ state: 'idle' }))
  autoUpdater.on('download-progress', (progress) => setUpdateState({
    state: 'downloading', percent: progress.percent, version: updateState.version,
  }))
  autoUpdater.on('update-downloaded', (info) => setUpdateState({ state: 'downloaded', version: info.version }))
  autoUpdater.on('error', (error) => setUpdateState({ state: 'error', message: error.message }))
  setTimeout(() => void autoUpdater.checkForUpdates().catch((error) => {
    setUpdateState({ state: 'error', message: String(error) })
  }), 10_000)
  setInterval(() => void autoUpdater.checkForUpdates().catch(() => undefined), 6 * 60 * 60 * 1000)
}

const ownsInstanceLock = process.env.MARIANA_E2E === '1' || app.requestSingleInstanceLock()
if (!ownsInstanceLock) app.quit()
else {
  app.on('second-instance', () => {
    trayActions.show()
  })
  app.whenReady().then(async () => {
    registerIpc()
    await createControlServer()
    await createWindow()
    ensureTray()
    startTerminal()
    configureUpdates()
  })
  app.on('before-quit', () => {
    quitting = true
    if (backendStartupTimer) clearTimeout(backendStartupTimer)
    backendStartupTimer = null
    terminalProcess?.write('exit y\r')
    terminalProcess?.kill()
    controlSocket?.destroy()
    controlSocket = null
    finishPendingControlRequests()
    tray?.destroy()
    tray = null
    trayAvailable = false
    controlServer?.close()
    if (process.platform !== 'win32') fs.rmSync(controlEndpoint, { force: true })
  })
  app.on('window-all-closed', () => {
    if (!quitting) trayActions.quit()
  })
  app.on('activate', trayActions.show)
}
