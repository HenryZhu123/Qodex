import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const root = process.argv[2];
const output = process.argv[3];
if (!root || !output) throw new Error("Usage: node extract_structured_sources.mjs <root> <output.json>");

async function walk(dir) {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...await walk(full));
    else if (/\.xlsx$/i.test(entry.name) && !/^~\$/.test(entry.name)) files.push(full);
  }
  return files;
}

const files = (await walk(root)).sort((a, b) => a.localeCompare(b, "zh-CN"));
const workbooks = [];
for (const file of files) {
  const stat = await fs.stat(file);
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(file));
  const sheets = [];
  for (const sheet of workbook.worksheets) {
    const used = sheet.getUsedRange(true);
    const values = used?.values ?? [];
    sheets.push({ name: sheet.name, values });
  }
  workbooks.push({ file, size: stat.size, modifiedAt: stat.mtime.toISOString(), sheets });
}

await fs.writeFile(output, JSON.stringify({ root, workbooks }, null, 2), "utf8");
console.log(JSON.stringify({
  files: workbooks.length,
  workbooks: workbooks.map((book) => ({
    file: book.file,
    size: book.size,
    modifiedAt: book.modifiedAt,
    sheets: book.sheets.map((sheet) => ({
      name: sheet.name,
      rows: sheet.values.length,
      cols: sheet.values.reduce((n, row) => Math.max(n, row.length), 0),
      firstRows: sheet.values.slice(0, 3),
    })),
  })),
}, null, 2));
