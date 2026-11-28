/** Stage only the portable player and one isolated Electron main entry point. */
import { execFileSync } from 'node:child_process';
import { cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const out = path.join(root,'build','electron-lite-release');
const stage = mkdtempSync(path.join(os.tmpdir(), 'mariana-electron-lite-'));
const metadata = JSON.parse(readFileSync(path.join(root,'package.json'),'utf8'));
const assets = path.join(stage,'web');
const argv = process.argv.slice(2);
const stageOnly = argv.includes('--stage-only');

function size(folder) {
  return readdirSync(folder,{withFileTypes:true}).reduce((total,item) => {
    const file = path.join(folder,item.name);
    return total + (item.isDirectory() ? size(file) : statSync(file).size);
  },0);
}

try {
  // A fresh staging directory keeps stale engine/model payloads out of builds.
  const python = process.env.MARIANA_BUILD_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  execFileSync(python,[path.join(root,'tools','build_web_player.py'),'--output',assets],{stdio:'inherit'});
  cpSync(path.join(root,'packaging','electron-lite','main.cjs'),path.join(stage,'main.cjs'));
  cpSync(path.join(root,'LICENSE'),path.join(stage,'LICENSE'));
  writeFileSync(path.join(stage,'package.json'),JSON.stringify({
    name:'mariana-player-lite', version:metadata.version, description:'Portable Mariana player',
    author:metadata.author, license:metadata.license, main:'main.cjs', private:true,
  },null,2));
  console.log('Mariana Lite application payload: ' + size(stage) + ' bytes before Electron runtime and compression.');
  if (stageOnly) {
    console.log(stage);
  } else {
    const { build } = await import('electron-builder');
    await build({publish:'never',dir:argv.includes('--dir'), config:{
      appId:'io.github.vivojay.mariana.lite', productName:'Mariana Player Lite',
      electronVersion:metadata.devDependencies.electron, compression:'maximum', asar:true,
      npmRebuild:false, files:['main.cjs','package.json','LICENSE','web/**'],
      directories:{app:stage,output:out},
      icon:path.join(assets,'icon-512.png'),
      win:{target:'nsis'}, mac:{target:'dmg', identity:null}, linux:{target:'AppImage', category:'AudioVideo'},
    }});
  }
} finally {
  if (!stageOnly) rmSync(stage,{recursive:true,force:true});
}
