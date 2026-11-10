"use strict";

const byId = (id) => document.getElementById(id);
const form = byId("author-form");
const controls = byId("author-controls");
const status = byId("author-status");
const message = byId("author-message");
const subjectNames = {data_structures: "数据结构", computer_organization: "计算机组成原理",
  operating_systems: "操作系统", computer_networks: "计算机网络"};
const failures = {NEEDS_MATERIAL: "材料不足", SELF_CHECK_FAILED: "未通过自检", INVALID_REQUEST: "请求需要调整",
  MODEL_UNAVAILABLE: "模型未完成", KNOWLEDGE_BASE_UNAVAILABLE: "知识库不可用",
  AUTHORING_CACHE_UNAVAILABLE: "缓存不可用", CLOUD_CONFIRMATION_REQUIRED: "请确认云端调用"};
let config;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text;
  return node;
}

function setStatus(label, tone, text) {
  status.textContent = label;
  status.dataset.tone = tone;
  message.textContent = text;
}

function clearPreview() {
  byId("author-question").hidden = true;
  for (const id of ["author-teacher", "author-design", "author-raw"]) byId(id).open = false;
  byId("author-design").hidden = byId("author-raw").hidden = true;
}

function renderQuestion(question, draft) {
  const student = question.student_view;
  if (typeof student?.stem !== "string") return;
  const instructor = question.instructor_view;
  const meta = question.metadata ?? {};
  const parts = Array.isArray(student.parts) ? student.parts : [];
  const options = Array.isArray(student.options) ? student.options : [];
  byId("question-meta").textContent = draft ? "模型原始候选 · 未通过验证" : [
    subjectNames[meta.subject], parts.length ? "综合题" : "单选题", meta.score && `${meta.score} 分`, meta.topic,
  ].filter(Boolean).join(" · ");
  byId("author-stem").textContent = student.stem;
  byId("author-parts").type = parts.length ? "1" : "A";
  byId("author-parts").replaceChildren(...(parts.length ? parts : options).map((part) =>
    element("li", part?.prompt ? `${part.prompt}（${part.score} 分）` : part?.text ?? "", "prose")));
  const teacher = byId("author-solutions");
  teacher.replaceChildren();
  byId("author-teacher").hidden = !instructor || typeof instructor !== "object";
  if (instructor && parts.length && Array.isArray(instructor.parts)) {
    if (instructor.grading_policy) teacher.append(element("p", instructor.grading_policy, "prose"));
    for (const [i, answer] of instructor.parts.entries()) {
      if (!answer) continue;
      teacher.append(element("h3", `第 ${i + 1} 问`), element("p", answer.solution ?? "", "prose"));
      if (Array.isArray(answer.scoring_points)) {
        const rubric = element("ul", "", "rubric");
        for (const point of answer.scoring_points.filter(Boolean)) {
          const expected = typeof point.expected === "string" ? point.expected : JSON.stringify(point.expected);
          rubric.append(element("li", `${point.points} 分 · ${point.criterion}\n${expected ?? ""}`, "prose"));
        }
        teacher.append(rubric);
      }
    }
  } else if (instructor) {
    const correct = options.findIndex((option) => option?.id === instructor.correct_option_id);
    if (correct !== -1) teacher.append(element("h3", `答案 ${"ABCD"[correct] ?? correct + 1}`));
    if (instructor.explanation) teacher.append(element("p", instructor.explanation, "prose"));
    for (const [i, option] of options.entries()) {
      const explanation = instructor.option_explanations?.[option?.id];
      if (explanation) teacher.append(element("p", `${"ABCD"[i] ?? i + 1} · ${explanation}`, "prose"));
    }
  }
  byId("author-question").hidden = false;
}

function renderResult(result, history) {
  const question = result.questions?.[0];
  const report = result.authoring_report;
  const preview = result.preview;
  const plan = report?.plan ?? question?.generator?.parameters?.brief_plan ?? preview?.unverified_plan;
  byId("author-json").textContent = JSON.stringify(result, null, 2);
  byId("author-raw").hidden = false;
  if (question && result.status === "GENERATED") {
    setStatus(history ? "历史实测 · 待审" : "生成完成 · 待审", "success",
      history ? "来自此前真实模型实验。本次仅回看已保存的题包。" : "题包通过命题自检，可展开查看答案与依据。");
    renderQuestion(question, false);
  } else {
    const stage = report?.stage ?? preview?.last_stage;
    setStatus(failures[result.status] ?? result.status, "failure", [stage, result.message].filter(Boolean).join(" · "));
    if (preview?.unverified_draft) renderQuestion(preview.unverified_draft, true);
  }
  const diagnostics = byId("author-diagnostics");
  diagnostics.replaceChildren();
  if (plan) {
    if (preview?.unverified_plan) diagnostics.append(element("p", "模型提出的计划 · 尚未通过验证"));
    for (const [label, text] of [["考查目标", plan.target], ["任务", plan.task], ["作答证据", plan.student_evidence]]) {
      if (text) diagnostics.append(element("h3", label), element("p", text, "prose"));
    }
  } else if (question?.pedagogy?.target) {
    diagnostics.append(element("h3", "考查目标"), element("p", question.pedagogy.target, "prose"));
  }
  if (question?.evidence_refs?.length) {
    const sources = element("ul", "");
    for (const ref of question.evidence_refs) sources.append(element("li", `${ref.source} · ${ref.anchor}`));
    diagnostics.append(element("h3", "材料出处"), sources);
  }
  if (question?.self_check?.checks?.length) diagnostics.append(element("p", `自检 · ${question.self_check.checks.join(" / ")}`));
  if (report?.details) diagnostics.append(element("p", typeof report.details === "string"
    ? report.details : JSON.stringify(report.details, null, 2), "prose"));
  if (preview?.model) diagnostics.append(element("p", `${preview.model} · 本次调用 ${preview.calls} 次`));
  byId("author-design").hidden = !diagnostics.childElementCount;
  if (!question && !byId("author-design").hidden) byId("author-design").open = true;
}

async function loadResult(url, options, history) {
  controls.disabled = true;
  clearPreview();
  setStatus(history ? "正在载入" : "正在命题", "idle", history ? "正在读取已保存题包。" : "模块正在取材、创作与自检。本机模型可能需要几分钟。");
  try {
    const response = await fetch(url, options);
    const result = await response.json();
    renderResult(result, history);
  } catch {
    setStatus("请求失败", "failure", "没有收到完整结果。请检查试题台是否还在运行。");
  } finally {
    controls.disabled = false;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!config || controls.disabled) return;
  const fields = new FormData(form);
  const request = {schema_version: "0.1", request_id: `workbench-${crypto.randomUUID()}`};
  for (const name of ["brief", "subject", "question_type"]) {
    const value = fields.get(name).trim();
    if (value) request[name] = value;
  }
  const excerpt = fields.get("material").trim();
  if (excerpt) request.evidence = [{id: "user-material", source: fields.get("source").trim() || "用户提供",
    version: "本次提交", anchor: "粘贴原文", summary: excerpt.slice(0, 360), excerpt, rules: []}];
  const confirmed = byId("cloud-confirmed").checked;
  byId("cloud-confirmed").checked = false;
  await loadResult("/api/author", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({request, cloud_confirmed: confirmed})}, false);
});

for (const button of form.querySelectorAll("[data-brief]")) button.addEventListener("click", () => {
  byId("brief").value = button.dataset.brief;
  byId("brief").focus();
});
byId("history-example").addEventListener("click", () => loadResult("/api/history-example", undefined, true));

async function initialize() {
  try {
    const response = await fetch("/api/workbench");
    if (!response.ok) throw new Error("Workbench configuration unavailable");
    config = await response.json();
    const cloud = config.provider === "deepseek";
    byId("provider-label").textContent = cloud ? "云端 DeepSeek · 逐次确认" : "本机 Ollama · 免费试跑";
    byId("knowledge-label").textContent = config.knowledge ? "已接教材知识库" : "可粘贴材料";
    byId("knowledge-label").hidden = false;
    byId("cloud-label").hidden = !cloud;
    byId("cloud-confirmed").required = cloud;
    byId("history-example").hidden = !config.sample;
    controls.disabled = false;
  } catch {
    setStatus("连接失败", "failure", "试题台配置暂不可读，请刷新页面。");
  }
}

initialize();
