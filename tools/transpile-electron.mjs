import { createHash, randomUUID } from 'node:crypto'
import fs from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import process from 'node:process'

const repository = path.resolve(import.meta.dirname, '..')
const sourceDirectory = path.join(repository, 'desktop')
const outputDirectory = path.join(repository, 'dist-electron')
const configPath = path.join(sourceDirectory, 'tsconfig.electron.json')
const cachePath = path.join(repository, 'node_modules', '.cache', 'mariana-electron', 'transpile.json')
const cacheVersion = 1
const hash = (value) => createHash('sha256').update(value).digest('hex')
const digestPattern = /^[a-f0-9]{64}$/
const relative = (filePath) => path.relative(repository, filePath)
const sourceName = (name) => (
  path.basename(name) === name
  && /\.(?:c?ts)$/.test(name)
  && !/\.(?:test|d)\.(?:c?ts)$/.test(name)
)
const outputName = (name) => `${path.parse(name).name}${name.endsWith('.cts') ? '.cjs' : '.js'}`

function fileHash(filePath) {
  try {
    return hash(fs.readFileSync(filePath))
  } catch (error) {
    if (['ENOENT', 'ENOTDIR', 'EISDIR'].includes(error.code)) return null
    throw error
  }
}

function directoryExists(directory) {
  try {
    return fs.statSync(directory).isDirectory()
  } catch (error) {
    if (error.code === 'ENOENT' || error.code === 'ENOTDIR') return false
    throw error
  }
}

function readCache() {
  try {
    const cache = JSON.parse(fs.readFileSync(cachePath, 'utf8'))
    if (cache.version !== cacheVersion || !cache.entries || Array.isArray(cache.entries)) return null
    if (!Array.isArray(cache.configurationInputs) || !cache.configurationInputs.length) return null
    if (!cache.configurationInputs.some((input) => input.kind === 'file' && input.path === relative(configPath))) {
      return null
    }
    for (const [name, entry] of Object.entries(cache.entries)) {
      if (!sourceName(name) || entry.output !== outputName(name)) return null
      if (!digestPattern.test(entry.sourceHash) || !digestPattern.test(entry.outputHash)) return null
    }
    if (cache.configurationInputs.some((input) => (
      typeof input.path !== 'string'
      || !['file', 'directory'].includes(input.kind)
      || (input.kind === 'file' && input.value !== null && !digestPattern.test(input.value))
      || (input.kind === 'directory' && typeof input.value !== 'boolean')
    ))) return null
    return cache
  } catch {
    // An absent, interrupted, or malformed cache is never proof of valid output.
    return null
  }
}

function writeAtomic(destination, contents) {
  const temporary = `${destination}.${process.pid}.${randomUUID()}.tmp`
  try {
    fs.writeFileSync(temporary, contents, 'utf8')
    fs.renameSync(temporary, destination)
  } finally {
    fs.rmSync(temporary, { force: true })
  }
}

// Hash content, not timestamps: preserved mtimes and replaced dependencies must
// not turn stale generated code into a cache hit. The compiler stays unloaded on
// a fully verified warm run.
const require = createRequire(import.meta.url)
const compilerPath = require.resolve('typescript')
const environmentHash = hash(JSON.stringify({
  version: cacheVersion,
  node: process.version,
  script: fileHash(import.meta.filename),
  compiler: [relative(compilerPath), fileHash(compilerPath)],
  packages: [
    'package.json', 'package-lock.json', 'npm-shrinkwrap.json', 'pnpm-lock.yaml', 'yarn.lock',
    relative(require.resolve('typescript/package.json')),
  ].map((name) => [name, fileHash(path.resolve(repository, name))]),
}))
const sources = fs.readdirSync(sourceDirectory, { withFileTypes: true })
  .filter((entry) => entry.isFile() && sourceName(entry.name))
  .map((entry) => entry.name)
  .sort()
  .map((name) => {
    const sourcePath = path.join(sourceDirectory, name)
    const contents = fs.readFileSync(sourcePath, 'utf8')
    return { name, sourcePath, contents, sourceHash: hash(contents), output: outputName(name) }
  })
const previous = readCache()
const configurationMatches = previous && previous.environmentHash === environmentHash
  && previous.configurationInputs.every((input) => (
    input.value === (input.kind === 'file'
      ? fileHash(path.resolve(repository, input.path))
      : directoryExists(path.resolve(repository, input.path)))
  ))
const reusable = new Map()
for (const source of sources) {
  const entry = configurationMatches ? previous.entries[source.name] : null
  if (entry && entry.sourceHash === source.sourceHash
    && entry.outputHash === fileHash(path.join(outputDirectory, source.output))) {
    reusable.set(source.name, entry)
  }
}
const namesChanged = !previous
  || JSON.stringify(Object.keys(previous.entries).sort()) !== JSON.stringify(sources.map((source) => source.name))
const compilerLoaded = !configurationMatches || reusable.size !== sources.length || namesChanged
let configurationInputs = previous?.configurationInputs ?? []
const generated = new Map()

if (compilerLoaded) {
  const ts = (await import('typescript')).default
  const inputs = new Map()
  const rememberInput = (kind, filePath) => {
    const name = relative(filePath)
    inputs.set(`${kind}:${name}`, {
      kind, path: name,
      value: kind === 'file' ? fileHash(filePath) : directoryExists(filePath),
    })
  }
  const host = {
    ...ts.sys,
    readFile: (filePath) => {
      rememberInput('file', filePath)
      return ts.sys.readFile(filePath)
    },
    fileExists: (filePath) => {
      rememberInput('file', filePath)
      return ts.sys.fileExists(filePath)
    },
    directoryExists: (directory) => {
      rememberInput('directory', directory)
      return ts.sys.directoryExists(directory)
    },
  }
  const diagnosticHost = {
    getCanonicalFileName: (name) => name,
    getCurrentDirectory: () => repository,
    getNewLine: () => '\n',
  }
  const config = ts.readConfigFile(configPath, host.readFile)
  if (config.error) throw new Error(ts.formatDiagnostic(config.error, diagnosticHost))
  const parsed = ts.parseJsonConfigFileContent(config.config, host, sourceDirectory, undefined, configPath)
  if (parsed.errors.length) throw new Error(ts.formatDiagnosticsWithColorAndContext(parsed.errors, diagnosticHost))
  const compilerOptions = { ...parsed.options, sourceMap: false, declaration: false }
  const diagnostics = []
  for (const { name, sourcePath, contents } of sources) {
    if (reusable.has(name)) continue
    const commonJs = sourcePath.endsWith('.cts')
    const moduleOptions = commonJs
      ? {
          module: ts.ModuleKind.NodeNext,
          moduleResolution: ts.ModuleResolutionKind.NodeNext,
        }
      : {
          module: ts.ModuleKind.ESNext,
          moduleResolution: ts.ModuleResolutionKind.Bundler,
        }
    const result = ts.transpileModule(contents, {
      compilerOptions: { ...compilerOptions, ...moduleOptions },
      fileName: sourcePath,
      reportDiagnostics: true,
    })
    diagnostics.push(...(result.diagnostics ?? []).filter(
      (diagnostic) => diagnostic.category === ts.DiagnosticCategory.Error,
    ))
    generated.set(name, result.outputText)
  }
  if (diagnostics.length) {
    process.stderr.write(ts.formatDiagnosticsWithColorAndContext(diagnostics, diagnosticHost))
    process.exitCode = 1
  }
  configurationInputs = [...inputs.values()]
}

if (!process.exitCode) {
  // Only remove outputs owned by a previous successful run, with their content
  // still intact. Untracked runtime assets and an existing dist directory stay.
  const currentNames = new Set(sources.map((source) => source.name))
  const obsolete = Object.entries(previous?.entries ?? {}).filter(([name]) => !currentNames.has(name))
  for (const [, entry] of obsolete) {
    const currentHash = fileHash(path.join(outputDirectory, entry.output))
    if (currentHash !== null && currentHash !== entry.outputHash) {
      throw new Error(`Refusing to remove modified stale Electron output: ${entry.output}`)
    }
  }
  fs.mkdirSync(outputDirectory, { recursive: true })
  const entries = {}
  for (const source of sources) {
    if (reusable.has(source.name)) {
      entries[source.name] = reusable.get(source.name)
    } else {
      const output = generated.get(source.name)
      const outputHash = hash(output)
      const destination = path.join(outputDirectory, source.output)
      if (fileHash(destination) !== outputHash) writeAtomic(destination, output)
      entries[source.name] = {
        sourceHash: source.sourceHash, output: source.output, outputHash,
      }
    }
  }
  for (const [, entry] of obsolete) {
    fs.rmSync(path.join(outputDirectory, entry.output), { force: true })
  }
  const cache = { version: cacheVersion, environmentHash, configurationInputs, entries }
  // Cache storage is optional. A read-only dependency directory may prevent it;
  // the generated runtime is still valid and subsequent starts can recompile.
  if (compilerLoaded) {
    try {
      fs.mkdirSync(path.dirname(cachePath), { recursive: true })
      writeAtomic(cachePath, JSON.stringify(cache))
    } catch (error) {
      if (!['EACCES', 'EPERM', 'EROFS'].includes(error.code)) throw error
    }
  }
  if (process.env.MARIANA_TRANSPILE_STATS === '1') {
    process.stdout.write(`${JSON.stringify({
      compilerLoaded, transpiled: generated.size, reused: reusable.size, removed: obsolete.length,
    })}\n`)
  }
}
