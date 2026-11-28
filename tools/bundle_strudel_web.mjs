// Build the optional browser synth with the pinned dependencies used by Electron.
import {readFile, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
import {build} from 'vite';

const project = fileURLToPath(new URL('..', import.meta.url));
const source = resolve(project, 'web/strudel-runtime');
const destination = resolve(project, 'build/strudel-runtime');
const bundle = await build({
  configFile: false,
  root: source,
  base: './',
  build: {
    target: 'es2022',
    outDir: destination,
    emptyOutDir: true,
    sourcemap: true,
    lib: {
      entry: resolve(source, 'runtime.js'),
      name: 'MarianaStrudelRuntime',
      formats: ['iife'],
      fileName: () => 'runtime.js',
      cssFileName: 'runtime',
    },
  },
});
const css = [bundle].flat().some(result => result.output.some(file => file.fileName === 'runtime.css'));
const html = await readFile(resolve(source, 'index.html'), 'utf8');
await writeFile(resolve(destination, 'index.html'), html.replace('<!-- style -->',
  css ? '<link rel="stylesheet" href="./runtime.css">' : ''));
