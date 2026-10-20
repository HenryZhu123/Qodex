import fs from "node:fs/promises";

const dump = JSON.parse(await fs.readFile(process.argv[2], "utf8"));
const [headers, ...matrix] = dump.values;
const rows = matrix.map((values, index) => ({
  __row: index + 2,
  ...Object.fromEntries(headers.map((h, i) => [h, values[i] ?? null])),
}));
const compact = (value) => String(value ?? "").replace(/\s+/g, "").trim();
const zhLen = (value) => (String(value ?? "").match(/[\u3400-\u9fff]/g) ?? []).length;
const explicitTitle = (row) => /名词解释|词语翻译|术语解释|解释下列各组概念|概念辨析|概念解释/.test(String(row.title ?? ""));
const looksLikeSentence = (text) =>
  /[？?]/.test(text) ||
  /(简述|论述|试述|说明|分析|什么|如何|为什么|请|比较|解释|指出|谈谈|概述|判断|选择|计算|证明|写出|列举|阐述|联系|结合|根据|下列|举例|回答|评述|阅读|翻译下列|改错|填空|作答)/.test(text) ||
  /（\s*）|\(\s*\)|_{2,}|[A-DＡ-Ｄ][\.、．]/.test(text);

const errorRows = rows.filter((row) => row.is_real_error === true);
const explicit = errorRows.filter(explicitTitle);
const nominal = errorRows.filter((row) => {
  const text = compact(row.content);
  return zhLen(text) > 0 && zhLen(text) <= 20 && !looksLikeSentence(text);
});
const unionMap = new Map([...explicit, ...nominal].map((row) => [row.id, row]));
const union = [...unionMap.values()].sort((a, b) => a.__row - b.__row);
const group = (arr, key) => Object.fromEntries(
  Object.entries(arr.reduce((acc, row) => {
    const value = String(row[key] ?? "<空>");
    acc[value] = (acc[value] ?? 0) + 1;
    return acc;
  }, {})).sort((a, b) => b[1] - a[1]),
);
const slim = (row) => ({
  row: row.__row,
  id: row.id,
  school: row.school,
  file_name: row.file_name,
  title: row.title,
  content: row.content,
  error_content: row.error_content,
  error_type: row.new_error_type ?? row.error_detailed_type,
  convert_note: row.convert_note,
  explicit_title: explicitTitle(row),
  zh_length: zhLen(row.content),
});
const out = {
  realErrors: errorRows.length,
  explicitCount: explicit.length,
  nominalCount: nominal.length,
  unionCount: union.length,
  unionTypes: group(union.map((row) => ({ ...row, effective_type: row.new_error_type ?? row.error_detailed_type })), "effective_type"),
  unionTitles: group(union, "title"),
  rows: union.map(slim),
};
await fs.writeFile(process.argv[3], JSON.stringify(out, null, 2), "utf8");
console.log(JSON.stringify({ ...out, rows: out.rows.slice(0, 30) }, null, 2));
