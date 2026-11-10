// Run through the team repository's tsx loader. No model request or API key required.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const piRoot = process.argv[2];
const python = process.argv[3];
assert.ok(piRoot && python, 'Provide Pi root and Python executable');
const { loadExtensions } = await import(pathToFileURL(resolve(piRoot, 'packages/coding-agent/src/core/extensions/loader.ts')).href);
const loaded = await loadExtensions([resolve(root, 'exam_assembly_agent/pi-extension.ts')], root);
assert.deepEqual(loaded.errors, []);
const tool = loaded.extensions[0].tools.get('exam_assembly').definition;
assert.equal(tool.name, 'exam_assembly');
const previous = process.env.QODEX_PYTHON;
try {
  process.env.QODEX_PYTHON = python;
  for (const [bank, requestFile, expected] of [
    ['development', 'request.json', 'STRUCTURAL_PASS'],
    ['repair_failure', 'repair_request.json', 'NEEDS_QUESTIONS'],
  ]) {
    const request = JSON.parse(await readFile(resolve(root, 'exam_assembly_agent/examples', requestFile), 'utf8'));
    const result = await tool.execute('offline-test', { bank, request }, undefined, undefined, {});
    assert.notEqual(result.isError, true);
    const output = JSON.parse(result.content[0].text);
    assert.equal(output.status, expected);
    assert.equal(output.mode, 'DEVELOPMENT_MOCK_BANK');
    if (expected === 'STRUCTURAL_PASS') {
      assert.equal(output.student_exam.length, 10);
      assert.ok(output.student_exam.every(q => !('answer' in q)));
      assert.ok(output.artifacts.answer_key);
    } else {
      assert.equal(output.student_exam, null);
      assert.ok(output.replenishment_request.slots.length);
    }
  }
  console.log('PASS: real Pi loader registered tool; Python execution returned success and shortage with artifacts. No model API used.');
} finally {
  if (previous === undefined) delete process.env.QODEX_PYTHON;
  else process.env.QODEX_PYTHON = previous;
}
