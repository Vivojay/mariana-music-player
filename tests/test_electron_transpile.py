"""Exercise the actual Electron preparation script in isolated repositories."""

import json
import os
import shutil
import statistics
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Frozen pre-cache implementation for paired measurements of the same source
# snapshot. The production script remains the only implementation under test.
BASELINE_SCRIPT = textwrap.dedent(r"""
    import fs from 'node:fs'
    import path from 'node:path'
    import process from 'node:process'
    import ts from 'typescript'
    const repository = path.resolve(import.meta.dirname, '..')
    const sourceDirectory = path.join(repository, 'desktop')
    const outputDirectory = path.join(repository, 'dist-electron')
    const configPath = path.join(sourceDirectory, 'tsconfig.electron.json')
    const config = ts.readConfigFile(configPath, ts.sys.readFile)
    if (config.error) {
      throw new Error(ts.formatDiagnostic(config.error, {
        getCanonicalFileName: (name) => name,
        getCurrentDirectory: () => repository,
        getNewLine: () => '\n',
      }))
    }
    const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, sourceDirectory)
    const compilerOptions = { ...parsed.options, sourceMap: false, declaration: false }
    const sources = fs.readdirSync(sourceDirectory, { withFileTypes: true })
      .filter((entry) => entry.isFile() && /\.(?:c?ts)$/.test(entry.name)
        && !entry.name.endsWith('.test.ts') && !entry.name.endsWith('.d.ts'))
      .map((entry) => path.join(sourceDirectory, entry.name))
    fs.mkdirSync(outputDirectory, { recursive: true })
    let failed = false
    for (const sourcePath of sources) {
      const source = fs.readFileSync(sourcePath, 'utf8')
      const commonJs = sourcePath.endsWith('.cts')
      const moduleOptions = commonJs
        ? { module: ts.ModuleKind.NodeNext, moduleResolution: ts.ModuleResolutionKind.NodeNext }
        : { module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler }
      const result = ts.transpileModule(source, {
        compilerOptions: { ...compilerOptions, ...moduleOptions },
        fileName: sourcePath, reportDiagnostics: true,
      })
      const errors = (result.diagnostics ?? []).filter(
        (diagnostic) => diagnostic.category === ts.DiagnosticCategory.Error,
      )
      if (errors.length) {
        failed = true
        process.stderr.write(ts.formatDiagnosticsWithColorAndContext(errors, {
          getCanonicalFileName: (name) => name,
          getCurrentDirectory: () => repository,
          getNewLine: () => '\n',
        }))
        continue
      }
      const extension = sourcePath.endsWith('.cts') ? '.cjs' : '.js'
      const destination = path.join(outputDirectory, `${path.parse(sourcePath).name}${extension}`)
      fs.writeFileSync(destination, result.outputText, 'utf8')
    }
    if (failed) process.exitCode = 1
""")


@pytest.fixture
def electron_workspace(tmp_path):
    node = shutil.which("node")
    compiler = ROOT / "node_modules" / "typescript"
    if node is None or not (compiler / "lib" / "typescript.js").is_file():
        pytest.skip("Electron preparation requires installed Node.js and TypeScript")
    workspace = tmp_path / "repository"
    (workspace / "tools").mkdir(parents=True)
    (workspace / "desktop").mkdir()
    (workspace / "node_modules" / "typescript" / "lib").mkdir(parents=True)
    shutil.copy2(ROOT / "tools" / "transpile-electron.mjs", workspace / "tools" / "transpile-electron.mjs")
    for relative in ("package.json", "lib/typescript.js"):
        shutil.copy2(compiler / relative, workspace / "node_modules" / "typescript" / relative)
    (workspace / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    (workspace / "desktop" / "tsconfig.electron.json").write_text(
        json.dumps({"compilerOptions": {"target": "ES2022"}, "include": ["*.ts", "*.cts"]}),
        encoding="utf-8",
    )
    return workspace, node


def prepare(workspace, node):
    started = time.perf_counter()
    result = subprocess.run(
        [node, "tools/transpile-electron.mjs"], cwd=workspace, capture_output=True, text=True, timeout=30,
        env={**os.environ, "MARIANA_TRANSPILE_STATS": "1"},
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    return result, elapsed_ms


def successful_prepare(workspace, node):
    result, _ = prepare(workspace, node)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def write_source(workspace, name="main.ts", contents="export const value: number = 1\n"):
    source = workspace / "desktop" / name
    source.write_text(contents, encoding="utf-8")
    return source


def read_cache(workspace):
    return json.loads((workspace / "node_modules" / ".cache" / "mariana-electron" / "transpile.json").read_text())


def test_actual_desktop_preparation_benchmark(electron_workspace):
    workspace, node = electron_workspace
    for source in (ROOT / "desktop").iterdir():
        if source.is_file() and source.suffix in {".ts", ".cts", ".json"}:
            shutil.copy2(source, workspace / "desktop" / source.name)
    script = workspace / "tools" / "transpile-electron.mjs"
    optimized_script = script.read_text(encoding="utf-8")
    script.write_text(BASELINE_SCRIPT, encoding="utf-8")
    baseline = []
    for _ in range(5):
        result, elapsed_ms = prepare(workspace, node)
        assert result.returncode == 0, result.stderr
        baseline.append(round(elapsed_ms, 2))
    baseline_outputs = {path.name: path.read_bytes() for path in (workspace / "dist-electron").iterdir()}
    script.write_text(optimized_script, encoding="utf-8")
    timings = []
    statistics_by_run = []
    for _ in range(5):
        result, elapsed_ms = prepare(workspace, node)
        assert result.returncode == 0, result.stderr
        timings.append(round(elapsed_ms, 2))
        statistics_by_run.append(json.loads(result.stdout))
    outputs = tuple((workspace / "dist-electron").glob("*.js")) + tuple(
        (workspace / "dist-electron").glob("*.cjs")
    )
    assert outputs
    assert {path.name: path.read_bytes() for path in outputs} == baseline_outputs
    assert statistics_by_run[0]["transpiled"] == len(outputs)
    assert all(not stats["compilerLoaded"] for stats in statistics_by_run[1:])
    print(
        f"Electron preparation: outputs={len(outputs)} baseline_ms={baseline} "
        f"baseline_median_ms={statistics.median(baseline)} optimized_ms={timings} "
        f"warm_median_ms={statistics.median(timings[1:])} stats={statistics_by_run}"
    )


def test_warm_run_skips_compiler_and_preserves_output_timestamps(electron_workspace):
    workspace, node = electron_workspace
    write_source(workspace)
    assert successful_prepare(workspace, node) == {"compilerLoaded": True, "transpiled": 1, "reused": 0, "removed": 0}
    output = workspace / "dist-electron" / "main.js"
    original = output.stat().st_mtime_ns
    assert successful_prepare(workspace, node) == {"compilerLoaded": False, "transpiled": 0, "reused": 1, "removed": 0}
    assert output.stat().st_mtime_ns == original


def test_one_changed_dependency_recompiles_even_with_preserved_timestamp(electron_workspace):
    workspace, node = electron_workspace
    write_source(workspace, contents="import { value } from './shared.js'\nexport { value }\n")
    source = write_source(workspace, "shared.ts")
    successful_prepare(workspace, node)
    original = source.stat()
    original_main = (workspace / "dist-electron" / "main.js").stat().st_mtime_ns
    write_source(workspace, "shared.ts", "export const value: number = 2\n")
    os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert successful_prepare(workspace, node) == {"compilerLoaded": True, "transpiled": 1, "reused": 1, "removed": 0}
    assert "value = 2" in (workspace / "dist-electron" / "shared.js").read_text()
    assert (workspace / "dist-electron" / "main.js").stat().st_mtime_ns == original_main
    assert successful_prepare(workspace, node)["compilerLoaded"] is False


def test_missing_or_modified_output_is_rebuilt_without_touching_other_outputs(electron_workspace):
    workspace, node = electron_workspace
    write_source(workspace)
    write_source(workspace, "shared.ts")
    successful_prepare(workspace, node)
    output = workspace / "dist-electron" / "main.js"
    original = output.read_text()
    output.write_text("broken output", encoding="utf-8")
    assert successful_prepare(workspace, node)["transpiled"] == 1
    assert output.read_text() == original
    output.unlink()
    assert successful_prepare(workspace, node)["transpiled"] == 1
    assert output.read_text() == original


def test_new_deleted_and_changed_module_extension_sources_are_handled_safely(electron_workspace):
    workspace, node = electron_workspace
    write_source(workspace)
    output = workspace / "dist-electron"
    output.mkdir()
    unowned = output / "existing-runtime.js"
    unowned.write_text("export const existing = true", encoding="utf-8")
    successful_prepare(workspace, node)
    source = write_source(workspace, "bridge.ts", "export const bridge: boolean = true")
    assert successful_prepare(workspace, node)["transpiled"] == 1
    source.rename(source.with_suffix(".cts"))
    stats = successful_prepare(workspace, node)
    assert stats["transpiled"] == 1
    assert stats["removed"] == 1
    assert not (output / "bridge.js").exists()
    assert (output / "bridge.cjs").is_file()
    source.with_suffix(".cts").unlink()
    stats = successful_prepare(workspace, node)
    assert stats["transpiled"] == 0
    assert stats["removed"] == 1
    assert not (output / "bridge.cjs").exists()
    assert unowned.read_text() == "export const existing = true"


def test_modified_stale_output_is_not_silently_deleted_or_accepted(electron_workspace):
    workspace, node = electron_workspace
    write_source(workspace)
    deleted = write_source(workspace, "old.ts")
    successful_prepare(workspace, node)
    deleted.unlink()
    output = workspace / "dist-electron" / "old.js"
    output.write_text("user-owned replacement", encoding="utf-8")
    result, _ = prepare(workspace, node)
    assert result.returncode != 0
    assert "Refusing to remove modified stale Electron output" in result.stderr
    assert output.read_text() == "user-owned replacement"


def test_invalid_source_cannot_publish_partial_output_or_cache_success(electron_workspace):
    workspace, node = electron_workspace
    write_source(workspace)
    write_source(workspace, "shared.ts")
    successful_prepare(workspace, node)
    before = (workspace / "dist-electron" / "main.js").read_bytes()
    cache = read_cache(workspace)
    write_source(workspace, contents="export const value = 200")
    invalid = write_source(workspace, "shared.ts", "export const = ;")
    result, _ = prepare(workspace, node)
    assert result.returncode != 0
    assert (workspace / "dist-electron" / "main.js").read_bytes() == before
    assert read_cache(workspace) == cache
    invalid.write_text("export const other = 5", encoding="utf-8")
    assert successful_prepare(workspace, node)["transpiled"] == 2


@pytest.mark.parametrize("dependency", ["package.json", "package-lock.json", "compiler", "script"])
def test_build_dependency_content_changes_invalidate_cache(electron_workspace, dependency):
    workspace, node = electron_workspace
    write_source(workspace)
    successful_prepare(workspace, node)
    previous = read_cache(workspace)["environmentHash"]
    if dependency == "compiler":
        changed = workspace / "node_modules" / "typescript" / "lib" / "typescript.js"
        changed.write_text(changed.read_text(encoding="utf-8") + "\n// dependency changed\n", encoding="utf-8")
    elif dependency == "script":
        changed = workspace / "tools" / "transpile-electron.mjs"
        changed.write_text(changed.read_text(encoding="utf-8") + "\n// preparation changed\n", encoding="utf-8")
    elif dependency == "package.json":
        (workspace / dependency).write_text('{"type":"module","version":"2.0.0"}', encoding="utf-8")
    else:
        (workspace / dependency).write_text('{"lockfileVersion":3}', encoding="utf-8")
    assert successful_prepare(workspace, node)["transpiled"] == 1
    assert read_cache(workspace)["environmentHash"] != previous
    assert successful_prepare(workspace, node)["compilerLoaded"] is False


def test_extended_configuration_changes_and_invalid_options_never_hit_cache(electron_workspace):
    workspace, node = electron_workspace
    write_source(workspace, contents="export const value = target?.nested\n")
    config = workspace / "desktop" / "tsconfig.electron.json"
    config.write_text('{"extends":"./base.json","include":["*.ts"]}', encoding="utf-8")
    base = workspace / "desktop" / "base.json"
    base.write_text('{"compilerOptions":{"target":"ES2022"}}', encoding="utf-8")
    successful_prepare(workspace, node)
    assert "target?.nested" in (workspace / "dist-electron" / "main.js").read_text()
    base.write_text('{"compilerOptions":{"target":"ES2018"}}', encoding="utf-8")
    assert successful_prepare(workspace, node)["transpiled"] == 1
    assert "target?.nested" not in (workspace / "dist-electron" / "main.js").read_text()
    base.write_text('{"compilerOptions":{"target":"not-a-target"}}', encoding="utf-8")
    result, _ = prepare(workspace, node)
    assert result.returncode != 0
    assert "--target" in result.stderr


def test_package_based_extended_configuration_is_tracked(electron_workspace):
    workspace, node = electron_workspace
    write_source(workspace)
    package = workspace / "node_modules" / "test-config"
    package.mkdir()
    (package / "package.json").write_text('{"name":"test-config","tsconfig":"base.json"}', encoding="utf-8")
    base = package / "base.json"
    base.write_text('{"compilerOptions":{"target":"ES2022"}}', encoding="utf-8")
    (workspace / "desktop" / "tsconfig.electron.json").write_text(
        '{"extends":"test-config","include":["*.ts"]}', encoding="utf-8",
    )
    successful_prepare(workspace, node)
    assert successful_prepare(workspace, node)["compilerLoaded"] is False
    base.write_text('{"compilerOptions":{"target":"ES2018"}}', encoding="utf-8")
    assert successful_prepare(workspace, node)["transpiled"] == 1


@pytest.mark.parametrize("contents", ["not JSON", "{}", '{"version":1,"entries":{"../../escape.ts":{}}}'])
def test_malformed_cache_is_a_miss_not_an_execution_or_deletion_instruction(electron_workspace, contents):
    workspace, node = electron_workspace
    write_source(workspace)
    successful_prepare(workspace, node)
    cache = workspace / "node_modules" / ".cache" / "mariana-electron" / "transpile.json"
    cache.write_text(contents, encoding="utf-8")
    assert successful_prepare(workspace, node)["transpiled"] == 1


def test_esm_and_commonjs_outputs_execute_and_tests_or_declarations_are_not_emitted(electron_workspace):
    workspace, node = electron_workspace
    write_source(workspace, contents="export const value: number = 42")
    write_source(workspace, "bridge.cts", "const value: number = 21; export = { value }")
    write_source(workspace, "ignored.test.ts", "export const = ;")
    write_source(workspace, "ignored.test.cts", "export const = ;")
    write_source(workspace, "types.d.ts", "declare const value: string")
    write_source(workspace, "types.d.cts", "declare const value: string")
    assert successful_prepare(workspace, node)["transpiled"] == 2
    check = subprocess.run(
        [node, "--input-type=module", "-e", (
            "import { createRequire } from 'node:module'; "
            "const require = createRequire(import.meta.url); "
            "const esm = await import('./dist-electron/main.js'); "
            "const cjs = require('./dist-electron/bridge.cjs'); "
            "if (esm.value !== 42 || cjs.value !== 21) process.exit(1)"
        )], cwd=workspace, capture_output=True, text=True, timeout=10,
    )
    assert check.returncode == 0, check.stderr
    assert sorted(path.name for path in (workspace / "dist-electron").iterdir()) == ["bridge.cjs", "main.js"]
