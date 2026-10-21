// Read UTF-8 arguments from a file so Windows PowerShell cannot split JSON/quotes/newlines.
import { readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';

const [argsFile, tsx, config, entry] = process.argv.slice(2);
const args = JSON.parse(readFileSync(argsFile, 'utf8'));
if (!Array.isArray(args) || args.some(x => typeof x !== 'string')) {
  throw new Error('Pi arguments must be a string array');
}
const child = spawn(process.execPath, [tsx, '--tsconfig', config, entry, ...args], {
  stdio: 'inherit', shell: false,
});
const timeout = Number(process.env.QODEX_PI_TIMEOUT_MS || 0);
let expired = false;
const timer = timeout > 0 ? setTimeout(() => {
  expired = true;
  console.error('[launcher] Test timed out. Inspect the saved trace; no success is assumed.');
  child.kill('SIGTERM');
}, timeout) : undefined;
child.on('error', () => {
  clearTimeout(timer);
  console.error('[launcher] Could not start the team Pi process.');
  process.exitCode = 1;
});
child.on('exit', code => {
  clearTimeout(timer);
  process.exitCode = expired ? 124 : code ?? 1;
});
