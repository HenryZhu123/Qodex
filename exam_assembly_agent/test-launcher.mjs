// Regression test through Windows PowerShell 5 and the real launcher, without Pi or an API.
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';

const moduleRoot = dirname(fileURLToPath(import.meta.url));
const folder = resolve(moduleRoot, 'outputs/launcher_tests', randomUUID());
const fakePi = join(folder, 'fake-pi');
mkdirSync(join(fakePi, 'node_modules/tsx/dist'), { recursive: true });
mkdirSync(join(fakePi, 'packages/coding-agent/src/experimental'), { recursive: true });
writeFileSync(join(fakePi, 'node_modules/tsx/dist/cli.mjs'), 'console.log(JSON.stringify(process.argv.slice(5)));');
writeFileSync(join(fakePi, 'packages/coding-agent/src/experimental/cli.ts'), '');
writeFileSync(join(fakePi, 'tsconfig.json'), '{}');
const expected = ['-p', '中文栈题 {"topic_counts":{"栈":2}}\nsecond line "quoted" and spaces'];
writeFileSync(join(folder, 'expected.json'), JSON.stringify(expected));
const psTest = join(folder, 'test.ps1');
writeFileSync(psTest, `param([string]$Launcher, [string]$PiRoot, [string]$ArgsPath)
$ErrorActionPreference='Stop'
$arguments=Get-Content -LiteralPath $ArgsPath -Raw -Encoding UTF8 | ConvertFrom-Json
& $Launcher -PiRoot $PiRoot -PiArguments $arguments
`);
const result = spawnSync('powershell.exe', ['-NoProfile', '-File', psTest,
  join(moduleRoot, 'run-team-pi.ps1'), fakePi, join(folder, 'expected.json')], { encoding: 'utf8', timeout: 30000 });
assert.equal(result.status, 0, result.stderr);
assert.deepEqual(JSON.parse(result.stdout.trim()), expected);
console.log('PASS: Windows PowerShell preserves Chinese, JSON quotes, spaces and newlines; no model API used.');
