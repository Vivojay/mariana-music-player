import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {runInNewContext} from 'node:vm';

const module = readFileSync(new URL('../web/player/companion-console.js',import.meta.url),'utf8');
const sandbox = {};
runInNewContext(module,sandbox);
const render = text => JSON.parse(JSON.stringify(sandbox.MarianaPairedConsole.styledOutput(text)));
const content = chunks => chunks.map(chunk=>chunk.text).join('');

test('Console retains text, progress lines, and safe terminal colors', () => {
  const chunks = render('┏━ Música\r\n\x1b[1;31mready\x1b[0m ❱ \x1b[38;2;20;140;240mplay\x1b[39m\rnext');
  assert.equal(content(chunks),'┏━ Música\nready ❱ play\nnext');
  assert.deepEqual(chunks.find(chunk=>chunk.text==='ready').style,{fontWeight:'bold',color:'#ef7886'});
  assert.deepEqual(chunks.find(chunk=>chunk.text==='play').style,{color:'rgb(20,140,240)'});
  assert.deepEqual(chunks.at(-1).style,{});
});

test('Console ignores cursor commands and does not turn control packets into links', () => {
  const chunks = render('visible\x1b[2J\x1b]8;;https://example.invalid/private\x07link text\x1b]8;;\x1b\\ ' +
    '\x1bPhidden payload\x1b\\<img src=x onerror=alert(1)>\x00');
  assert.equal(content(chunks),'visiblelink text <img src=x onerror=alert(1)>');
  assert.equal(content(render('plain\x1b]0;nothing after this')), 'plain');
  assert.equal(content(render('plain\x1b[1;')), 'plain');
});

test('Console supports the indexed palette and discards invalid color parameters', () => {
  const chunks = render('\x1b[48;5;196mred background\x1b[0m\x1b[38;2;1;999;3mout of range');
  assert.deepEqual(chunks[0].style,{backgroundColor:'rgb(255,0,0)'});
  assert.deepEqual(chunks[1].style,{});
});
