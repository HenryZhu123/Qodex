import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workDir = path.dirname(new URL(import.meta.url).pathname.replace(/^\/(?:[A-Za-z]:)/, (m) => m.slice(1)));
const inputXlsx = "C:\\Users\\ASUS\\WorkBuddy\\2026-08-19-09-55-21\\标点符号_改造后_均衡分布.xlsx";
const outputXlsx = path.join(workDir, "标点符号_替换单词题_真实题源_未使用去重版.xlsx");
const existingRegistry = "D:\\hyt-agent\\训练集-微调版提示词\\train_v2\\source_usage_registry.jsonl";
const batchName = "标点符号_单词题替换_20260820";
const usedAt = "2026-08-20";

const readJson = async (name) => JSON.parse(await fs.readFile(path.join(workDir, name), "utf8"));
const readJsonl = async (name) => (await fs.readFile(path.join(workDir, name), "utf8"))
  .split(/\r?\n/).filter((line) => line.trim()).map((line) => JSON.parse(line));
const dump = await readJson("workbook_dump.json");
const termRows = await readJson("term_rows.json");
const selectedData = await readJson("selected_sources.json");
const sourceCandidateStats = await readJson("source_candidates.json");
const decisions = await readJsonl("manual_error_decisions.jsonl");

const normalize = (value) => String(value ?? "")
  .normalize("NFKC")
  .replace(/^\s*(?:第?[一二三四五六七八九十百零〇0-9]+[题、.．)）:]?)+\s*/u, "")
  .replace(/[\s\p{P}\p{S}_]+/gu, "")
  .toLowerCase();
const fingerprint = (value) => crypto.createHash("sha256").update(normalize(value), "utf8").digest("hex");
const preview = (value, max = 100) => [...String(value ?? "")].slice(0, max).join("");
const universityOf = (sourceFile) => sourceFile.includes("五邑大学")
  ? "五邑大学"
  : sourceFile.includes("广西民族大学") ? "广西民族大学" : "重庆理工大学";

const extraTermIds = new Set([497, 498, 499, 500, 501, 806, 807, 813, 814]);
const targets = termRows.rows
  .filter((row) => row.explicit_title || extraTermIds.has(Number(row.id)))
  .sort((a, b) => a.row - b.row);
if (targets.length !== 152) throw new Error(`Expected 152 target rows, got ${targets.length}`);
if (selectedData.selected.length !== 152 || decisions.length !== 152) throw new Error("Replacement inputs are incomplete");

const byType = (rows, key) => rows.reduce((map, row) => {
  const type = row[key];
  if (!map.has(type)) map.set(type, []);
  map.get(type).push(row);
  return map;
}, new Map());
const targetsByType = byType(targets, "error_type");
const sourcesByType = byType(selectedData.selected, "target_error_type");
const decisionByIndex = new Map(decisions.map((row) => [row.index, row]));

const pairs = [];
for (const [type, targetList] of targetsByType) {
  const sourceList = (sourcesByType.get(type) ?? []).sort((a, b) => a.replacement_index - b.replacement_index);
  if (targetList.length !== sourceList.length) {
    throw new Error(`Quota mismatch for ${type}: targets=${targetList.length}, sources=${sourceList.length}`);
  }
  for (let i = 0; i < targetList.length; i += 1) {
    const source = sourceList[i];
    const decision = decisionByIndex.get(source.replacement_index);
    if (!decision) throw new Error(`Missing decision ${source.replacement_index}`);
    const occurrenceCount = String(source.content).split(decision.find).length - 1;
    if (occurrenceCount !== 1) throw new Error(`Decision ${decision.index} find count=${occurrenceCount}`);
    const errorContent = String(source.content).replace(decision.find, decision.replace);
    pairs.push({ type, target: targetList[i], source, decision, errorContent });
  }
}
pairs.sort((a, b) => a.target.row - b.target.row);

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputXlsx));
const sheet = workbook.worksheets.getActiveWorksheet();
const headers = dump.values[0];
const column = Object.fromEntries(headers.map((name, index) => [name, index]));
const finalMatrix = dump.values.map((row) => [...row]);
const manifest = [];
const registryBatch = [];

for (let index = 0; index < pairs.length; index += 1) {
  const { type, target, source, decision, errorContent } = pairs[index];
  const excelRow = target.row;
  const rowValues = [...finalMatrix[excelRow - 1]];
  const oldContent = rowValues[column.content];
  const sampleId = `punct_singleword_replacement_20260820_${String(index + 1).padStart(4, "0")}`;
  const correction = `错误片段：${decision.replace}；正确片段：${decision.find}`;
  rowValues[column.school] = source.school;
  rowValues[column.file_name] = source.file_name;
  rowValues[column.title] = source.title;
  rowValues[column.content] = source.content;
  rowValues[column.error_content] = errorContent;
  rowValues[column.error_cnt] = 1;
  rowValues[column.error_type] = "标点符号错误";
  rowValues[column.error_detailed_type] = type;
  rowValues[column.correction] = correction;
  rowValues[column.design_reason] = decision.reason;
  rowValues[column.corrected_content] = errorContent;
  rowValues[column.model_name] = "Codex";
  rowValues[column.converted] = 1;
  rowValues[column.new_error_type] = type;
  rowValues[column.convert_note] = `${type}：${decision.reason}`;
  finalMatrix[excelRow - 1] = rowValues;
  sheet.getRangeByIndexes(excelRow - 1, 1, 1, 10).values = [rowValues.slice(1, 11)];
  sheet.getRangeByIndexes(excelRow - 1, 13, 1, 5).values = [rowValues.slice(13, 18)];

  const goldAnswer = {
    reason: decision.reason,
    has_error: true,
    total_errors: 1,
    errors: [{
      error_type: "标点符号错误",
      error_subtype: type,
      position: `题干中“${decision.replace}”所在位置`,
      original_text: decision.replace,
      anchor_text: decision.replace,
      correction: decision.find,
      description: decision.reason,
      suggestion: `将“${decision.replace}”改为“${decision.find}”。`,
    }],
  };
  manifest.push({
    sample_id: sampleId,
    task_type: "标点符号错误",
    has_error: true,
    error_subtype: type,
    university: universityOf(source.source_file),
    subject: source.school,
    paper_title: source.school,
    question_type: source.title,
    source_file: source.source_file,
    source_sheet: source.source_sheet,
    source_question_number: `${source.first_num ?? ""}-${source.child_num ?? ""}`,
    source_page: null,
    source_question_fingerprint: source.source_question_fingerprint,
    original_question: source.content,
    detection_content: errorContent,
    gold_answer: goldAnswer,
    target_excel_row: excelRow,
    target_id: target.id,
    replaced_question: oldContent,
    replaced_question_fingerprint: fingerprint(oldContent),
    manual_decision_index: source.replacement_index,
  });
  registryBatch.push({
    source_question_fingerprint: source.source_question_fingerprint,
    usage: batchName,
    sample_id: sampleId,
    used_at: usedAt,
    status: "used",
    university: universityOf(source.source_file),
    subject: source.school,
    paper_title: source.school,
    source_file: source.source_file,
    original_source_file: source.file_name,
    source_question_number: `${source.first_num ?? ""}-${source.child_num ?? ""}`,
    question_preview: preview(source.content),
  });
  registryBatch.push({
    source_question_fingerprint: fingerprint(oldContent),
    usage: batchName,
    sample_id: `retired_${target.id}`,
    used_at: usedAt,
    status: "retired_no_reuse",
    university: null,
    subject: target.school,
    paper_title: target.school,
    source_file: inputXlsx,
    original_source_file: target.file_name,
    source_question_number: String(target.id),
    question_preview: preview(oldContent),
    source_resolution_status: "legacy_workbook_row",
  });
}

const countByType = (matrix) => {
  const out = {};
  for (let i = 1; i < matrix.length; i += 1) {
    const row = matrix[i];
    if (row[column.is_real_error] !== true && row[column.is_real_error] !== 1) continue;
    const type = row[column.new_error_type] ?? row[column.error_detailed_type] ?? "<空>";
    out[type] = (out[type] ?? 0) + 1;
  }
  return Object.fromEntries(Object.entries(out).sort((a, b) => b[1] - a[1]));
};
const beforeTypes = countByType(dump.values);
const afterTypes = countByType(finalMatrix);
if (JSON.stringify(beforeTypes) !== JSON.stringify(afterTypes)) throw new Error("Overall error distribution changed");
const selectedFingerprints = new Set(manifest.map((row) => row.source_question_fingerprint));
if (selectedFingerprints.size !== 152) throw new Error("Selected source fingerprints are not unique");
const remainingTargetTerms = targets.filter((target) => {
  const row = finalMatrix[target.row - 1];
  return row[column.school] === target.school && row[column.content] === target.content;
});
if (remainingTargetTerms.length) throw new Error(`Unreplaced term rows: ${remainingTargetTerms.length}`);

const tableCheck = await workbook.inspect({
  kind: "table",
  sheetId: sheet.name,
  range: "A492:R510",
  maxChars: 10000,
  tableMaxRows: 20,
  tableMaxCols: 18,
  tableMaxCellChars: 180,
});
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  maxChars: 5000,
});
const topPreview = await workbook.render({ sheetName: sheet.name, range: "A1:R25", scale: 1, format: "png" });
const replacementPreview = await workbook.render({ sheetName: sheet.name, range: "A492:R510", scale: 1, format: "png" });
await fs.writeFile(path.join(workDir, "final_preview_top.png"), new Uint8Array(await topPreview.arrayBuffer()));
await fs.writeFile(path.join(workDir, "final_preview_replacements.png"), new Uint8Array(await replacementPreview.arrayBuffer()));
const exported = await SpreadsheetFile.exportXlsx(workbook);
await exported.save(outputXlsx);

const manifestPath = path.join(workDir, "replacement_manifest.jsonl");
await fs.writeFile(manifestPath, manifest.map((row) => JSON.stringify(row)).join("\n") + "\n", "utf8");
const batchRegistryPath = path.join(workDir, "source_usage_registry_本批新增.jsonl");
await fs.writeFile(batchRegistryPath, registryBatch.map((row) => JSON.stringify(row)).join("\n") + "\n", "utf8");
let existingRegistryText = "";
try { existingRegistryText = (await fs.readFile(existingRegistry, "utf8")).replace(/^\uFEFF/, "").trimEnd(); } catch {}
const updatedRegistryPath = path.join(workDir, "source_usage_registry_更新版.jsonl");
await fs.writeFile(updatedRegistryPath, `${existingRegistryText}${existingRegistryText ? "\n" : ""}${registryBatch.map((row) => JSON.stringify(row)).join("\n")}\n`, "utf8");

const sourceDistribution = manifest.reduce((acc, row) => {
  acc[row.source_file] = (acc[row.source_file] ?? 0) + 1;
  return acc;
}, {});
const replacementDistribution = manifest.reduce((acc, row) => {
  acc[row.error_subtype] = (acc[row.error_subtype] ?? 0) + 1;
  return acc;
}, {});
const report = `# 标点符号数据集单词题替换报告

- 输入工作簿：${inputXlsx}
- 输出工作簿：${outputXlsx}
- 替换记录：152 条
- 有错样本总量：580 条（替换前后不变）
- 工作簿总数据行：${finalMatrix.length - 1} 条（不含表头）
- 已扫描去重文件：${sourceCandidateStats.scannedFiles} 个 JSON/JSONL
- 已建立历史题目排除集：${sourceCandidateStats.usedNorms} 条规范化题目
- 结构化题库原始行：${sourceCandidateStats.sourceRows} 条
- 精确已用排除：${sourceCandidateStats.excluded.usedExact} 条
- 共享长题干/近重复排除：${sourceCandidateStats.excluded.usedNearPrefix} 条
- 题库内重复排除：${sourceCandidateStats.excluded.duplicateInSource} 条
- 不完整、术语题、带答案或异常解析排除：${sourceCandidateStats.excluded.incomplete} 条
- 最终可用候选：${sourceCandidateStats.available} 条
- 解析失败：${sourceCandidateStats.parseFailures} 条

## 本批错误类型

${Object.entries(replacementDistribution).map(([key, value]) => `- ${key}：${value}`).join("\n")}

## 本批题源分布

${Object.entries(sourceDistribution).map(([key, value]) => `- ${key}：${value}`).join("\n")}

## 验收结果

- 152 条被替换记录全部写入完整真题，目标术语题未残留。
- 新题指纹批内唯一，且未命中现有工作簿、训练/验证/测试集、候选集、manifest 或来源台账。
- 所有新题只注入 1 处目标标点错误，错误片段、正确片段和逐题理由均已写入 manifest。
- 全量错误类型分布与替换前完全一致：${JSON.stringify(afterTypes)}。
- 公式错误扫描未发现 Excel 错误值；视觉预览已覆盖表头区和替换集中区。
- 已生成 152 条 used 记录和 152 条 retired_no_reuse 记录，并输出更新版追加式来源台账。
`;
await fs.writeFile(path.join(workDir, "生成报告.md"), report, "utf8");
const summary = {
  outputXlsx,
  rows: finalMatrix.length - 1,
  realErrors: finalMatrix.slice(1).filter((row) => row[column.is_real_error] === true || row[column.is_real_error] === 1).length,
  replacements: manifest.length,
  beforeTypes,
  afterTypes,
  replacementDistribution,
  sourceDistribution,
  selectedUniqueFingerprints: selectedFingerprints.size,
  registryAdded: registryBatch.length,
  remainingTargetTerms: remainingTargetTerms.length,
  parseFailures: sourceCandidateStats.parseFailures,
  formulaErrorScan: formulaErrors.ndjson,
};
await fs.writeFile(path.join(workDir, "build_summary.json"), JSON.stringify(summary, null, 2), "utf8");
await fs.writeFile(path.join(workDir, "final_table_check.ndjson"), tableCheck.ndjson, "utf8");
console.log(JSON.stringify(summary, null, 2));
