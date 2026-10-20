import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const input = process.argv[2];
const outputDir = process.argv[3];
if (!input || !outputDir) {
  throw new Error("Usage: node inspect_workbooks.mjs <input.xlsx> <output-dir>");
}

await fs.mkdir(outputDir, { recursive: true });
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(input));
const summary = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 12000,
  tableMaxRows: 8,
  tableMaxCols: 12,
  tableMaxCellChars: 180,
});

const active = workbook.worksheets.getActiveWorksheet();
const used = active.getUsedRange(true);
const values = used?.values ?? [];
const formulas = used?.formulas ?? [];
const style = await workbook.inspect({
  kind: "computedStyle",
  sheetId: active.name,
  range: "A1:L8",
  maxChars: 8000,
});
const preview = await workbook.render({
  sheetName: active.name,
  range: "A1:L25",
  scale: 1,
  format: "png",
});
await fs.writeFile(
  path.join(outputDir, "input_preview.png"),
  new Uint8Array(await preview.arrayBuffer()),
);
await fs.writeFile(
  path.join(outputDir, "workbook_dump.json"),
  JSON.stringify({ input, activeSheet: active.name, values, formulas }, null, 2),
  "utf8",
);
await fs.writeFile(path.join(outputDir, "inspect_summary.ndjson"), summary.ndjson, "utf8");
await fs.writeFile(path.join(outputDir, "inspect_style.ndjson"), style.ndjson, "utf8");

console.log(JSON.stringify({
  activeSheet: active.name,
  rows: values.length,
  cols: values.reduce((n, row) => Math.max(n, row.length), 0),
  firstRows: values.slice(0, 6),
  summaryChars: summary.ndjson.length,
  styleChars: style.ndjson.length,
}));
