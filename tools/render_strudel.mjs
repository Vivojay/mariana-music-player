// Read validated project data from stdin. Only the bundled parser executes.
import { readFileSync } from 'node:fs';
import '../web/player/strudel-pattern.js';

try {
  const { source, seconds } = JSON.parse(readFileSync(0, 'utf8'));
  const wav = await globalThis.MarianaStrudelPattern.render(source, seconds);
  process.stdout.write(Buffer.from(await wav.arrayBuffer()));
} catch (error) {
  process.stderr.write(String(error.message) + '\n');
  process.exitCode = 1;
}
