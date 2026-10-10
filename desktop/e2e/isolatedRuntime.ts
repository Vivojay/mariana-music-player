import { build } from 'vite'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import ts from 'typescript'

/** Build current host/renderer sources without replacing a running app's files. */
export async function createIsolatedRuntime(prefix = 'mariana-native-runtime-') {
  const repository = path.resolve('.')
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), prefix))
  const dependencyLink = path.join(directory, 'node_modules')
  const cleanup = () => {
    // Remove the junction itself first; never traverse installed dependencies.
    fs.rmSync(dependencyLink, { force: true })
    fs.rmSync(directory, { recursive: true, force: true, maxRetries: 20, retryDelay: 100 })
  }
  try {
    const output = path.join(directory, 'dist-electron')
    fs.mkdirSync(output)
    fs.symlinkSync(path.join(repository, 'node_modules'), dependencyLink, 'junction')
    const { version } = JSON.parse(fs.readFileSync(path.join(repository, 'package.json'), 'utf8')) as { version: string }
    fs.writeFileSync(path.join(directory, 'package.json'), JSON.stringify({
      name: 'mariana-native-validation', version, type: 'module', main: 'dist-electron/main.js',
    }))
    for (const name of fs.readdirSync(path.join(repository, 'desktop'))) {
      if (!/\.(?:c?ts)$/.test(name) || /\.(?:test|d)\.(?:c?ts)$/.test(name)) continue
      const common = name.endsWith('.cts')
      const result = ts.transpileModule(fs.readFileSync(path.join(repository, 'desktop', name), 'utf8'), {
        fileName: name, reportDiagnostics: true, compilerOptions: {
          target: ts.ScriptTarget.ES2022, esModuleInterop: true,
          module: common ? ts.ModuleKind.NodeNext : ts.ModuleKind.ESNext,
          moduleResolution: common ? ts.ModuleResolutionKind.NodeNext : ts.ModuleResolutionKind.Bundler,
        },
      })
      if (result.diagnostics?.some((entry) => entry.category === ts.DiagnosticCategory.Error)) {
        throw new Error(`Invalid native fixture source: ${name}`)
      }
      fs.writeFileSync(path.join(output, `${path.parse(name).name}${common ? '.cjs' : '.js'}`), result.outputText)
    }
    await build({ configFile: path.join(repository, 'vite.config.ts'), logLevel: 'error',
      build: { outDir: path.join(directory, 'dist'), emptyOutDir: true },
    })
    fs.mkdirSync(path.join(directory, 'res'))
    fs.copyFileSync(path.join(repository, 'res', 'welcome_banner.png'), path.join(directory, 'res', 'welcome_banner.png'))
    // One actual backend per isolated application, using original resources.
    fs.writeFileSync(path.join(directory, 'main.py'), [
      'import os, runpy, sys', `root = ${JSON.stringify(repository)}`,
      'os.chdir(root)', 'sys.path.insert(0, root)',
      'os.environ["MARIANA_RESOURCE_DIR"] = root',
      'if os.environ.get("MARIANA_NATIVE_STARTUP_PROFILE") == "1":',
      '    import cProfile, json',
      '    profiler = cProfile.Profile()',
      '    profiler.enable()',
      '    import main',
      '    original_prompt = main.mainprompt',
      '    def measured_prompt():',
      '        profiler.disable()',
      '        rows = []',
      '        for entry in sorted(profiler.getstats(), key=lambda item: item.totaltime, reverse=True):',
      '            code = entry.code',
      '            if isinstance(code, str): continue',
      '            label = os.path.basename(os.path.dirname(code.co_filename)) + "/" + os.path.basename(code.co_filename)',
      '            if code.co_name.startswith("_") or code.co_name == "<module>": continue',
      '            rows.append({"file": label, "function": code.co_name, "calls": entry.callcount, "totalMs": round(entry.totaltime * 1000, 2), "selfMs": round(entry.inlinetime * 1000, 2)})',
      '            if len(rows) == 25: break',
      '        print("Startup profile " + json.dumps(rows), flush=True)',
      '        main.mainprompt = original_prompt',
      '        return original_prompt()',
      '    main.mainprompt = measured_prompt',
      '    main.startup()',
      'else:',
      '    runpy.run_path(os.path.join(root, "main.py"), run_name="__main__")', '',
    ].join('\n'))
    return { directory, cleanup,
      python: path.join(repository, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'),
    }
  } catch (error) {
    cleanup()
    throw error
  }
}
