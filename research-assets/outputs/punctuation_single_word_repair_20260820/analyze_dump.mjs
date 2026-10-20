import fs from "node:fs/promises";

const dump = JSON.parse(await fs.readFile(process.argv[2], "utf8"));
const [headers, ...matrix] = dump.values;
const rows = matrix.map((values, index) => Object.fromEntries(headers.map((h, i) => [h, values[i] ?? null])));
const textOf = (row) => String(row.error_content ?? row.content ?? "").trim();
const visibleLen = (text) => [...String(text).replace(/\s+/g, "")].length;
const chineseLen = (text) => (String(text).match(/[\u3400-\u9fff]/g) ?? []).length;
const hasSentenceStructure = (text) => /[，。！？；：、,.!?;:（）()“”‘’《》【】\n]|_{2,}|[A-DＡ-Ｄ][\.、]/.test(String(text));
const candidates = rows.filter((row) => {
  const text = textOf(row);
  const len = visibleLen(text);
  const zh = chineseLen(text);
  return row.is_real_error === true && zh > 0 && len <= 18 && !hasSentenceStructure(text);
});

const bucket = (arr, keyFn) => {
  const out = {};
  for (const row of arr) {
    const key = String(keyFn(row) ?? "<空>");
    out[key] = (out[key] ?? 0) + 1;
  }
  return Object.fromEntries(Object.entries(out).sort((a, b) => b[1] - a[1]));
};

const shortErrorRows = rows.filter((r) => r.is_real_error === true && visibleLen(textOf(r)) <= 30);
const allErrorRows = rows.filter((r) => r.is_real_error === true);
const result = {
  rows: rows.length,
  realErrors: allErrorRows.length,
  realErrorTypes: bucket(allErrorRows, (r) => r.new_error_type ?? r.error_detailed_type),
  shortErrorCountsByMaxLen: Object.fromEntries([6, 8, 10, 12, 15, 18, 20, 25, 30].map((n) => [n, allErrorRows.filter((r) => visibleLen(textOf(r)) <= n).length])),
  shortTypes: bucket(shortErrorRows, (r) => r.new_error_type ?? r.error_detailed_type),
  candidateCount: candidates.length,
  candidateTypes: bucket(candidates, (r) => r.new_error_type ?? r.error_detailed_type),
  candidates: candidates.map((r) => ({
    row: rows.indexOf(r) + 2,
    id: r.id,
    school: r.school,
    file_name: r.file_name,
    title: r.title,
    content: r.content,
    error_content: r.error_content,
    corrected_content: r.corrected_content,
    error_detailed_type: r.error_detailed_type,
    new_error_type: r.new_error_type,
    correction: r.correction,
    design_reason: r.design_reason,
    convert_note: r.convert_note,
  })),
  allShortRows: allErrorRows
    .filter((r) => visibleLen(r.content ?? "") <= 30)
    .map((r) => ({
      row: rows.indexOf(r) + 2,
      id: r.id,
      school: r.school,
      title: r.title,
      original_length: visibleLen(r.content ?? ""),
      content: r.content,
      error_content: r.error_content,
      new_error_type: r.new_error_type,
      convert_note: r.convert_note,
    })),
};
await fs.writeFile(process.argv[3], JSON.stringify(result, null, 2), "utf8");
console.log(JSON.stringify({
  rows: result.rows,
  realErrors: result.realErrors,
  realErrorTypes: result.realErrorTypes,
  shortErrorCountsByMaxLen: result.shortErrorCountsByMaxLen,
  candidateCount: result.candidateCount,
  candidateTypes: result.candidateTypes,
  allShortRows: result.allShortRows.length,
}, null, 2));
