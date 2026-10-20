import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const inputPath = "/Users/softzephyr/Downloads/事实-逻辑错误.xlsx";
const outputDir = "/Users/softzephyr/Desktop/hyt-agent/outputs/fact_logic_quality_audit";
const outputPath = outputDir + "/事实-逻辑错误_质量问题清单.xlsx";

const issues = [
  [23, "中", "错误类型标注不准确", "“四种”改为“三种”需要依赖旅游动机分类的外部知识判错，题内没有列举四类形成自相矛盾，因此不是严格的题内逻辑数量错误。", "若保留此题，将细分类改为事实数量或分类数量错误；建议新增 FACT_QUANTITY。", "FACT_QUANTITY", ""],
  [36, "中", "错误类型标注不准确", "“2.5美元”改成“2.5元”是依赖外部来源确认的币种或单位事实错误，不是题内逻辑数量矛盾。", "建议新增或使用 FACT_UNIT；如只能使用现有类别，可归入事实数量错误，不应标为 LOGIC_QUANTITY。", "FACT_UNIT", ""],
  [80, "中", "错误类型标注不准确", "“40亿美元”改成“400亿美元”属于金额或数量事实错误，却被标为 FACT_PLACE。", "改为 FACT_QUANTITY；同时增加枚举校验，避免金额、年份等被分到地点类。", "FACT_QUANTITY", ""],
  [82, "中", "错误类型标注不准确", "“2020年初”改成“2019年初”属于时间事实错误，却被标为 FACT_PLACE。", "改为 FACT_TIME。", "FACT_TIME", ""],
  [83, "中", "错误类型标注不准确", "“20世纪初”改成“19世纪初”属于时间或年代事实错误，却被标为 FACT_PLACE。", "改为 FACT_TIME。", "FACT_TIME", ""],
  [86, "中", "错误类型标注不准确", "国家一级保护动物改成二级属于法定保护等级或属性错误，却被标为 FACT_PLACE。", "建议改为 FACT_STATUS 或 FACT_ATTRIBUTION，不应归入地点错误。", "FACT_STATUS", ""],
  [127, "中", "造错触及核心作答对象", "把“聚苯乙烯”改为“聚氯乙烯”直接改变了题目要求制备的目标聚合物，并使指定的活性阴离子聚合路线不可行。该错误非常显眼，也与其他记录中“不能改动被考查任务对象”的跳过标准不一致。", "优先跳过此题；若必须造错，应修改旁置的聚合条件、引发剂归属等可核验事实，并确保不改变题目要求完成的核心任务。", "NO_ELIGIBLE_SPAN", ""],
  [159, "中", "错误数量字段不一致", "实际只有一个根错误，即发布日期年份由2023改为2022，design_reason 也写明“仅单点时间错误”，但 error_cnt 填为2。", "将 error_cnt 改为1，并增加自动校验：错误数量必须与 correction 条目数及语义改动数一致。", "FACT_TIME", ""],
  [168, "中", "错误类型标注不准确", "“1.3万亿斤”改为“1.5万亿斤”需要外部政策文件才能判错，题内没有另一数值与其形成矛盾，因此不应标为 LOGIC_QUANTITY。", "改为 FACT_QUANTITY；只有在题内存在可直接计算或前后冲突时才使用 LOGIC_QUANTITY。", "FACT_QUANTITY", ""],
  [212, "高", "错误无法证真", "A公司属于匿名案例，题目没有其他时间锚点或外部来源。把“2020年开始实行目标管理”改成“2021年”无法证明是事实错误；理由仅引用原题文本，属于循环证明。", "标记为 NO_ELIGIBLE_SPAN 并跳过。禁止用“原题如此写”作为事实证据，事实类错误必须提供独立来源或题内真相锚点。", "NO_ELIGIBLE_SPAN", ""],
  [255, "严重", "造错方向反转", "原题写企业文化理论于20世纪70年代提出，造错后改为80年代；但 design_reason 自己说明通行观点是20世纪80年代初形成。造错文本反而更接近正确事实，correction 会把它改回错误答案。", "直接删除并重新生成。先把正确底稿改成“企业文化理论于20世纪80年代初形成和兴起”，再选择其他错误年代进行造错。", "FACT_TIME", "https://www.tup.tsinghua.edu.cn/upload/books/yz/105211-01.pdf"]
];

const issueMap = new Map(issues.map((x) => [x[0], x]));
const inputBlob = await FileBlob.load(inputPath);
const sourceBook = await SpreadsheetFile.importXlsx(inputBlob);
const sourceSheet = sourceBook.worksheets.getItemAt(0);
const sourceValues = sourceSheet.getUsedRange(true).values;
const headers = sourceValues[0];
const records = sourceValues.slice(1).map((row) => Object.fromEntries(headers.map((h, i) => [h, row[i]])));

const workbook = Workbook.create();
const detail = workbook.worksheets.add("问题题目清单");
const summary = workbook.worksheets.add("数据集问题汇总");
detail.showGridLines = false;
summary.showGridLines = false;
detail.tabColor = "#7F1D1D";
summary.tabColor = "#1F4E78";

detail.getRange("A2:J2").merge();
detail.getRange("A2").values = [["事实-逻辑错误错题集质量问题清单"]];
detail.getRange("A3:J3").merge();
detail.getRange("A3").values = [["共记录11道需要淘汰、重造、修订事实表述或修正元数据的题目。原始题目文本完整保留。"]];

const detailHeaders = [["ID", "Excel原行", "严重程度", "问题类别", "原题原文", "当前造错题", "错误原因", "修改建议", "建议细分类", "参考来源"]];
detail.getRange("A5:J5").values = detailHeaders;
const detailRows = records
  .filter((r) => issueMap.has(Number(r.id)))
  .map((r) => {
    const x = issueMap.get(Number(r.id));
    return [Number(r.id), Number(r.id) + 1, x[1], x[2], r.content ?? "", r.error_content ?? "", x[3], x[4], x[5], x[6]];
  });
detail.getRange("A6").write(detailRows);
detail.tables.add("A5:J" + (5 + detailRows.length), true, "IssueQuestionTable").style = "TableStyleMedium2";

detail.getRange("A2:J2").format = { font: { name: "Arial", size: 16, bold: true, color: "#111827" } };
detail.getRange("A3:J3").format = { font: { name: "Arial", size: 10, color: "#4B5563" } };
detail.getRange("A5:J5").format = { fill: "#7F1D1D", font: { name: "Arial", bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };
detail.getRange("A6:J" + (5 + detailRows.length)).format = { font: { name: "Arial", size: 10, color: "#111827" }, verticalAlignment: "top", wrapText: true };
detail.getRange("A6:D" + (5 + detailRows.length)).format.horizontalAlignment = "center";
detail.getRange("I6:I" + (5 + detailRows.length)).format.horizontalAlignment = "center";
detail.getRange("A2:A" + (5 + detailRows.length)).format.columnWidth = 8;
detail.getRange("B2:B" + (5 + detailRows.length)).format.columnWidth = 10;
detail.getRange("C2:C" + (5 + detailRows.length)).format.columnWidth = 10;
detail.getRange("D2:D" + (5 + detailRows.length)).format.columnWidth = 24;
detail.getRange("E2:F" + (5 + detailRows.length)).format.columnWidth = 55;
detail.getRange("G2:H" + (5 + detailRows.length)).format.columnWidth = 42;
detail.getRange("I2:I" + (5 + detailRows.length)).format.columnWidth = 22;
detail.getRange("J2:J" + (5 + detailRows.length)).format.columnWidth = 38;
detail.getRange("A5:J5").format.rowHeight = 34;
detail.getRange("A6:J" + (5 + detailRows.length)).format.rowHeight = 140;
detail.freezePanes.freezeRows(5);

summary.getRange("A2:F2").merge();
summary.getRange("A2").values = [["数据集问题汇总"]];
const successCount = records.filter((r) => Number(r.error_cnt || 0) > 0).length;
const skipCount = records.length - successCount;
const blankErrorCount = records.filter((r) => Number(r.error_cnt || 0) === 0 && (r.error_content === null || r.error_content === "")).length;
const copiedSkipCount = records.filter((r) => Number(r.error_cnt || 0) === 0 && String(r.error_content || "") === String(r.content || "")).length;
summary.getRange("A4:B10").values = [
  ["指标", "数量"],
  ["总记录数", records.length],
  ["成功造错", successCount],
  ["跳过", skipCount],
  ["跳过且 error_content 为空", blankErrorCount],
  ["跳过且复制原题", copiedSkipCount],
  ["本清单问题题目", detailRows.length]
];

summary.getRange("D4:F4").values = [["登记细分类", "数量", "占成功造错比例"]];
const positive = records.filter((r) => Number(r.error_cnt || 0) > 0);
const typeCounts = new Map();
for (const r of positive) {
  const key = r.error_detailed_type || "未填写";
  typeCounts.set(key, (typeCounts.get(key) || 0) + 1);
}
const typeRows = [...typeCounts.entries()].sort((a, b) => b[1] - a[1]).map(([k, v]) => [k, v, v / successCount]);
summary.getRange("D5").write(typeRows);

summary.getRange("A13:D13").values = [["数据集级问题", "影响", "修改建议", "涉及记录"]];
summary.getRange("A14:D16").values = [
  ["跳过记录输出协议不一致", "140条跳过记录将 error_content 留空，125条跳过记录复制原题；空值记录同时表现为 is_content_same=False，可能被下游误判为成功改写。", "统一协议：跳过时复制原题并设 is_content_same=True；或新增 generation_status=SKIPPED，禁止仅依据 is_content_same 判断。", "265条跳过记录"],
  ["错误类型过度集中", "登记结果中 FACT_TIME 14条，占成功样本35%；LOGIC_QUANTITY 8条，占20%。且几乎全部是单个年份、数字或名词替换。", "将时间类控制在20%以内，真正依靠题内证据的逻辑错误提高到至少35%，补充因果倒置、条件冲突、定义边界和单位维度错误。", "40条成功造错记录"],
  ["细分类标签存在系统性错位", "金额、年份、保护等级等被误分为地点类；依赖外部事实的数值错误被标成题内逻辑错误。", "增加基于实体类型的标签校验，并区分 FACT_QUANTITY、FACT_UNIT、FACT_STATUS 与 LOGIC_QUANTITY。", "ID 23、36、80、82、83、86、168"]
];

summary.getRange("A2:F2").format = { font: { name: "Arial", size: 16, bold: true, color: "#111827" } };
summary.getRange("A4:B4").format = { fill: "#1F4E78", font: { name: "Arial", bold: true, color: "#FFFFFF" }, horizontalAlignment: "center" };
summary.getRange("D4:F4").format = { fill: "#1F4E78", font: { name: "Arial", bold: true, color: "#FFFFFF" }, horizontalAlignment: "center" };
summary.getRange("A13:D13").format = { fill: "#7F1D1D", font: { name: "Arial", bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };
summary.getRange("A5:F" + (4 + typeRows.length)).format.font = { name: "Arial", size: 10, color: "#111827" };
summary.getRange("A14:D16").format = { font: { name: "Arial", size: 10, color: "#111827" }, verticalAlignment: "top", wrapText: true };
summary.getRange("F5:F" + (4 + typeRows.length)).format.numberFormat = "0.0%";
summary.getRange("A2:A17").format.columnWidth = 28;
summary.getRange("B2:B17").format.columnWidth = 16;
summary.getRange("C2:C17").format.columnWidth = 42;
summary.getRange("D2:D17").format.columnWidth = 28;
summary.getRange("E2:E17").format.columnWidth = 12;
summary.getRange("F2:F17").format.columnWidth = 18;
summary.getRange("A14:D16").format.rowHeight = 90;
summary.freezePanes.freezeRows(4);

detail.getRange("C6:C" + (5 + detailRows.length)).conditionalFormats.add("containsText", { text: "严重", format: { fill: "#FECACA", font: { bold: true, color: "#991B1B" } } });
detail.getRange("C6:C" + (5 + detailRows.length)).conditionalFormats.add("containsText", { text: "高", format: { fill: "#FED7AA", font: { bold: true, color: "#9A3412" } } });

workbook.recalculate();
await fs.mkdir(outputDir, { recursive: true });
const detailPreview = await workbook.render({ sheetName: "问题题目清单", range: "A1:J12", scale: 1, format: "png" });
await fs.writeFile(outputDir + "/问题题目清单_预览.png", new Uint8Array(await detailPreview.arrayBuffer()));
const summaryPreview = await workbook.render({ sheetName: "数据集问题汇总", range: "A1:F17", scale: 1, format: "png" });
await fs.writeFile(outputDir + "/数据集问题汇总_预览.png", new Uint8Array(await summaryPreview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

const check = await workbook.inspect({ kind: "table", range: "问题题目清单!A2:J21", include: "values,formulas", tableMaxRows: 21, tableMaxCols: 10, maxChars: 9000 });
console.log(check.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan" });
console.log(errors.ndjson);
console.log(JSON.stringify({ outputPath, detailRows: detailRows.length, successCount, skipCount, blankErrorCount, copiedSkipCount }));
