import { app, BrowserWindow, clipboard, ipcMain, shell } from 'electron'
import electronUpdater from 'electron-updater'
import { randomBytes } from 'node:crypto'
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import * as pty from 'node-pty'
import type { BackendEvent, UpdateState } from './shared.js'

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
let terminalProcess: pty.IPty | null = null
let controlServer: net.Server | null = null
let terminalHistory = ''
let terminalControlTail = ''
let quitting = false
let playbackState = 'idle'
let sleepActive = false
let backendReady = false
let backendShutdownAcknowledged = false
let backendExitClosesView = true
let backendSafeOverride: boolean | null = null
let updateState: UpdateState = { state: app.isPackaged ? 'idle' : 'disabled' }
let updatePreparationTimer: NodeJS.Timeout | null = null

const safeToInstall = () => (
  backendSafeOverride ?? (['idle', 'paused', 'failed'].includes(playbackState) && !sleepActive)
)

const send = <T>(channel: string, value: T) => {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send(channel, value)
}

const setUpdateState = (next: UpdateState) => {
  updateState = { ...next, safeToInstall: safeToInstall() }
  send('updates:state', updateState)
}

function validateSender(event: Electron.IpcMainEvent | Electron.IpcMainInvokeEvent): boolean {
  return Boolean(mainWindow && event.sender === mainWindow.webContents)
}

function handleBackendEvent(event: BackendEvent) {
  if (event.event === 'playback') playbackState = String(event.payload.state ?? 'idle')
  if (event.event === 'sleep') sleepActive = Boolean(event.payload.active)
  if (event.event === 'update-safe') backendSafeOverride = Boolean(event.payload.safe)
  if (event.event === 'ready') {
    backendReady = true
    fs.writeFileSync(path.join(app.getPath('userData'), 'healthy.json'), JSON.stringify({
      version: app.getVersion(), timestamp: Date.now(),
    }))
  }
  if (event.event === 'fatal-error' || event.event === 'shutdown-ack') backendReady = false
  if (event.event === 'shutdown-ack') backendShutdownAcknowledged = true
  if (event.event === 'update-prepared' && updateState.state === 'downloaded') {
    if (updatePreparationTimer) clearTimeout(updatePreparationTimer)
    quitting = true
    backendExitClosesView = false
    terminalProcess?.write('exit y\r')
    setTimeout(() => autoUpdater.quitAndInstall(false, true), 1200)
  }
  send('backend:event', event)
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
          const message = JSON.parse(line) as BackendEvent & { token?: string }
          if (message.token === controlToken && typeof message.event === 'string') handleBackendEvent(message)
        } catch {
          // Ignore malformed local control messages without affecting the PTY.
        }
      }
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
  })
  if (usesViteRenderer) await mainWindow.loadURL('http://127.0.0.1:5173')
  else await mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
  mainWindow.on('closed', () => { mainWindow = null })
}

function registerIpc() {
  ipcMain.handle('backend:snapshot', async (event) => {
    if (!validateSender(event)) throw new Error('Invalid IPC sender')
    return { ready: backendReady, playbackState, sleepActive }
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
    mainWindow?.close()
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
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })
  app.whenReady().then(async () => {
    registerIpc()
    await createControlServer()
    await createWindow()
    startTerminal()
    configureUpdates()
  })
  app.on('before-quit', () => {
    quitting = true
    terminalProcess?.write('exit y\r')
    terminalProcess?.kill()
    controlServer?.close()
    if (process.platform !== 'win32') fs.rmSync(controlEndpoint, { force: true })
  })
  app.on('window-all-closed', () => {
    if (!quitting) app.quit()
  })
}
