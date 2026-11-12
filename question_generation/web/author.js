"use strict";

const byId = (id) => document.getElementById(id);

const STAGES = [
  {key: "intake", label: "需求解析", short: "解析", hint: "读取需求、科目与范围"},
  {key: "materials", label: "素材检索", short: "取材", hint: "在知识库中定位可引用材料"},
  {key: "plan", label: "需求细化", short: "细化", hint: "拟定考查目标、任务与作答证据", model: 0},
  {key: "author", label: "题目创作", short: "创作", hint: "写出题面、答案与评分", model: 1},
  {key: "verify", label: "结构自检", short: "自检", hint: "检查题面、引文与依赖结构"},
  {key: "reader", label: "独立解答", short: "盲解", hint: "看不见答案地独立求解", model: 2},
  {key: "audit", label: "反例审计", short: "审计", hint: "寻找反例、歧义与评分漏洞", model: 3},
  {key: "delivery", label: "交付自检", short: "交付", hint: "汇总结果并标记待审"},
];
const STAGE_BY_NAME = {"需求细化": "plan", "题目创作": "author", "独立解答": "reader", "反例与解析审计": "audit"};
const STAGE_INDEX = Object.fromEntries(STAGES.map((stage, index) => [stage.key, index]));
const STATE_LABEL = {pending: "待执行", active: "进行中", passed: "通过", failed: "未通过", skipped: "未执行"};

const subjectNames = {data_structures: "数据结构", computer_organization: "计算机组成原理",
  operating_systems: "操作系统", computer_networks: "计算机网络"};
const typeNames = {single_choice: "单选题", comprehensive: "综合题"};
const objectiveNames = {analyze: "分析", diagnose: "诊断", transfer: "迁移", design: "设计"};
const qualityNames = {answerability: "可答性", depth: "推理深度", distractors: "干扰项", clarity: "清晰度"};
const checkNames = {answer_agreement: "答案一致", ambiguity: "歧义", grounding: "材料依据", grading: "评分",
  witness_alignment: "见证对齐", reasoning_necessity: "推理必要性", requirements: "需求落实",
  counterfactual: "反事实", scope: "范围"};
const failures = {NEEDS_MATERIAL: "材料不足", SELF_CHECK_FAILED: "未通过自检", INVALID_REQUEST: "请求需要调整",
  MODEL_UNAVAILABLE: "模型未完成", KNOWLEDGE_BASE_UNAVAILABLE: "知识库不可用",
  AUTHORING_CACHE_UNAVAILABLE: "缓存不可用", CLOUD_CONFIRMATION_REQUIRED: "请确认云端调用",
  UNSUPPORTED_REQUEST: "请求不受支持", QUEUE_VERSION_CONFLICT: "版本冲突", QUEUE_UNAVAILABLE: "待审队列不可用"};

const form = byId("author-form");
const controls = byId("author-controls");
const status = byId("author-status");
const message = byId("author-message");
const track = byId("pipeline-track");
const stageList = byId("stage-list");
const eventLog = byId("event-log");
const blocked = byId("blocked-banner");

let config;
let timer;

function blankStages() {
  return Object.fromEntries(STAGES.map((stage) => [stage.key, {
    state: "pending", elapsed: null, tokens: null, summary: null, error: null, startedAt: null,
  }]));
}

const run = {
  active: false,
  clockStart: 0,
  totalElapsed: null,
  calls: 0,
  tokens: 0,
  stages: blankStages(),
  result: null,
  history: false,
  openStage: null,
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function stageFor(key) {
  return STAGES[STAGE_INDEX[key]];
}

function setStatus(label, tone, text) {
  status.textContent = label;
  status.dataset.tone = tone;
  if (text != null) message.textContent = text;
}

function fmtDuration(seconds) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.round(seconds % 60)}s`;
}

function fmtTokens(tokens) {
  if (!tokens) return "—";
  const total = (tokens.prompt_tokens || 0) + (tokens.completion_tokens || 0);
  return total ? total.toLocaleString("zh-CN") : "—";
}

function addLog(text, tone = "info") {
  const placeholder = eventLog.querySelector(".log-empty");
  if (placeholder) placeholder.remove();
  const item = element("li", "", `log-line log-${tone}`);
  item.append(element("span", new Date().toLocaleTimeString("zh-CN", {hour12: false}), "log-time"));
  item.append(element("span", "", "log-dot"));
  item.append(element("span", text, "log-text"));
  eventLog.append(item);
  while (eventLog.children.length > 220) eventLog.firstElementChild.remove();
  const nearBottom = eventLog.scrollHeight - eventLog.scrollTop - eventLog.clientHeight < 90;
  if (nearBottom) eventLog.scrollTop = eventLog.scrollHeight;
}

function clearLog() {
  eventLog.replaceChildren(element("li", "等待开始…", "log-empty"));
}

function setStage(key, state, patch = {}) {
  const current = run.stages[key];
  if (!current) return;
  Object.assign(current, patch, {state});
  if (state === "active" && !current.startedAt) current.startedAt = performance.now();
  updatePipeline();
  renderStages();
  tick();
}

function updatePipeline() {
  for (const step of track.children) {
    const state = run.stages[step.dataset.key]?.state ?? "pending";
    step.dataset.state = state;
    const icon = step.querySelector(".pipe-icon");
    if (icon) icon.textContent = state === "passed" ? "✓" : state === "failed" ? "!" :
      state === "active" ? "●" : state === "skipped" ? "–" : "·";
    step.setAttribute("aria-label", `${stageFor(step.dataset.key).label}：${STATE_LABEL[state]}`);
  }
  const passed = STAGES.filter((stage) => run.stages[stage.key].state === "passed").length;
  const active = STAGES.some((stage) => run.stages[stage.key].state === "active");
  const percent = Math.max(0, Math.min(100, ((passed + (active ? 0.45 : 0)) / STAGES.length) * 100));
  byId("progress-fill").style.width = `${percent}%`;
  byId("progress-rail").setAttribute("aria-valuenow", String(Math.round(percent)));
  byId("live-dot").dataset.active = run.active ? "true" : "false";
  const failedStage = STAGES.find((stage) => run.stages[stage.key].state === "failed");
  const activeStage = STAGES.find((stage) => run.stages[stage.key].state === "active");
  byId("current-stage-label").textContent = activeStage ? `正在进行：${activeStage.label}` :
    failedStage ? `阻断于：${failedStage.label}` :
      run.result?.status === "GENERATED" || run.history ? "全部阶段完成" :
        passed ? `已完成 ${passed} / ${STAGES.length} 段` : "尚未开始";
}

function tick() {
  const elapsed = run.totalElapsed ?? (run.clockStart ? (performance.now() - run.clockStart) / 1000 : 0);
  byId("metric-elapsed").textContent = fmtDuration(elapsed);
  byId("metric-calls").textContent = String(run.calls);
  byId("metric-tokens").textContent = run.tokens ? run.tokens.toLocaleString("zh-CN") : "0";
  for (const stage of STAGES) {
    const state = run.stages[stage.key];
    const node = stageList.querySelector(`[data-stage="${stage.key}"] .stage-time`);
    if (!node) continue;
    const live = state.state === "active" && state.startedAt
      ? (performance.now() - state.startedAt) / 1000 : state.elapsed;
    node.textContent = live != null ? fmtDuration(live) : "";
  }
}

function startClock() {
  run.clockStart = performance.now();
  clearInterval(timer);
  timer = setInterval(tick, 200);
  tick();
}

function stopClock() {
  clearInterval(timer);
  timer = null;
  tick();
}

function resetRun() {
  run.active = false;
  run.clockStart = 0;
  run.totalElapsed = null;
  run.calls = 0;
  run.tokens = 0;
  run.stages = blankStages();
  run.result = null;
  run.history = false;
  run.openStage = null;
  clearLog();
  byId("author-question").hidden = true;
  byId("preview-empty").hidden = false;
  byId("review-badge").hidden = true;
  byId("author-teacher").open = false;
  byId("author-design").hidden = true;
  byId("author-raw").hidden = true;
  blocked.hidden = true;
  updatePipeline();
  renderStages();
  tick();
}

/* ---------- pipeline and stage cards ---------- */

function buildPipeline() {
  track.replaceChildren();
  for (const [index, stage] of STAGES.entries()) {
    const item = element("li", "", "pipe-step");
    item.dataset.key = stage.key;
    item.dataset.state = "pending";
    item.tabIndex = 0;
    const node = element("span", "", "pipe-node");
    node.append(element("span", "", "pipe-icon"));
    item.append(node, element("span", stage.label, "pipe-label"), element("span", stage.hint, "pipe-hint"));
    const focusStage = () => {
      const card = stageList.querySelector(`[data-stage="${stage.key}"]`);
      if (card) {
        const output = card.querySelector("details.stage-output");
        if (output) output.open = true;
        card.scrollIntoView({behavior: "smooth", block: "nearest"});
        card.classList.add("stage-card-flash");
        setTimeout(() => card.classList.remove("stage-card-flash"), 900);
      }
    };
    item.addEventListener("click", focusStage);
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); focusStage(); }
    });
    item.setAttribute("data-index", String(index + 1));
    track.append(item);
  }
}

function renderStages() {
  stageList.replaceChildren();
  for (const [index, stage] of STAGES.entries()) {
    const state = run.stages[stage.key];
    const card = element("li", "", "stage-card");
    card.dataset.state = state.state;
    card.dataset.stage = stage.key;

    const header = element("div", "", "stage-head");
    header.append(element("span", String(index + 1).padStart(2, "0"), "stage-index"));
    const title = element("div", "", "stage-title");
    title.append(element("h4", stage.label), element("p", stage.hint));
    header.append(title);
    const badge = element("span", STATE_LABEL[state.state], "stage-badge");
    header.append(badge);
    header.append(element("span", "", "stage-time"));
    card.append(header);

    if (state.state !== "pending") {
      const meta = element("div", "", "stage-meta");
      if (state.tokens) meta.append(element("span", `${fmtTokens(state.tokens)} tokens`));
      if (state.elapsed != null) meta.append(element("span", fmtDuration(state.elapsed)));
      if (meta.childElementCount) card.append(meta);
    }

    const body = element("div", "", "stage-body");
    if (state.error) {
      const error = element("div", "", "stage-error");
      error.append(element("strong", "阻断原因"), element("p", state.error, "prose"));
      body.append(error);
    } else if (state.summary) {
      const output = element("details", "", "stage-output");
      output.open = run.openStage === stage.key;
      const summaryNode = element("summary", "", "stage-output-summary");
      summaryNode.append(element("span", "查看阶段输出"));
      const line = summaryLine(stage.key, state.summary);
      if (line) summaryNode.append(element("span", line, "stage-output-preview"));
      output.append(summaryNode, renderSummary(stage.key, state.summary));
      body.append(output);
    } else if (state.state === "active") {
      body.append(element("p", "正在等待模型返回这一阶段的完整输出…", "stage-pending-note"));
    } else if (state.state === "skipped") {
      body.append(element("p", "前面的阶段未通过，本阶段没有执行。", "stage-pending-note"));
    } else if (state.state === "pending") {
      body.append(element("p", "尚未开始。", "stage-pending-note"));
    }
    card.append(body);
    stageList.append(card);
  }
  tick();
}

function kvGrid(pairs) {
  const dl = element("dl", "", "kv-grid");
  for (const [label, value] of pairs) {
    if (!value) continue;
    dl.append(element("dt", label), element("dd", value, "prose"));
  }
  return dl;
}

function chips(label, values) {
  if (!Array.isArray(values) || !values.length) return null;
  const box = element("div", "", "chip-row");
  box.append(element("span", label, "chip-label"));
  for (const value of values) box.append(element("span", String(value), "chip"));
  return box;
}

function renderSummary(key, summary) {
  const wrap = element("div", "", "summary");
  if (summary.gaps) {
    const gap = element("div", "", "stage-error");
    gap.append(element("strong", "材料缺口"));
    const ul = element("ul", "", "plain-list");
    for (const item of summary.gaps) ul.append(element("li", item));
    gap.append(ul);
    wrap.append(gap);
    return wrap;
  }
  if (key === "plan") {
    wrap.append(kvGrid([
      ["考查内容", summary.topic], ["题型", typeNames[summary.question_type] || summary.question_type],
      ["能力目标", objectiveNames[summary.objective] || summary.objective],
      ["推理任务", summary.task], ["作答证据", summary.student_evidence],
    ]));
    const area = chips("章节", summary.syllabus_areas);
    if (area) wrap.append(area);
    const query = chips("定向检索", summary.material_queries);
    if (query) wrap.append(query);
    if (summary.evidence_count) wrap.append(element("p", `已选用 ${summary.evidence_count} 条材料。`, "stage-footnote"));
    return wrap;
  }
  if (key === "author") {
    const shape = element("div", "", "chip-row");
    shape.append(element("span", summary.shape || "候选题", "chip chip-accent"));
    wrap.append(shape);
    if (summary.stem) wrap.append(element("blockquote", summary.stem, "stage-stem prose"));
    if (Array.isArray(summary.options) && summary.options.length) {
      const list = element("ol", "", "stage-options");
      list.type = "A";
      for (const option of summary.options) list.append(element("li", option));
      wrap.append(list);
    }
    if (Array.isArray(summary.parts) && summary.parts.length) {
      const list = element("ol", "", "plain-list");
      for (const part of summary.parts) list.append(element("li", part));
      wrap.append(list);
    }
    return wrap;
  }
  if (key === "reader") {
    wrap.append(kvGrid([["独立答案", summary.answer]]));
    if (summary.quality) {
      const meters = element("div", "", "quality-grid");
      for (const [name, value] of Object.entries(summary.quality)) {
        const meter = element("div", "", "quality-meter");
        meter.append(element("span", qualityNames[name] || name, "quality-name"));
        const dots = element("span", "", "quality-dots");
        for (let i = 0; i < 2; i += 1) dots.append(element("i", "", i < value ? "on" : ""));
        meter.append(dots);
        meters.append(meter);
      }
      wrap.append(meters);
    }
    if (summary.depth_evidence) wrap.append(element("p", summary.depth_evidence, "stage-footnote prose"));
    if (summary.issues?.length) wrap.append(chips("问题", summary.issues));
    return wrap;
  }
  if (key === "audit") {
    const verdict = element("div", "", "chip-row");
    verdict.append(element("span", summary.valid === true ? "审计通过" : "审计未通过",
      `chip ${summary.valid === true ? "chip-pass" : "chip-fail"}`));
    wrap.append(verdict);
    if (summary.checks && Object.keys(summary.checks).length) {
      const grid = element("div", "", "check-grid");
      for (const [name, check] of Object.entries(summary.checks)) {
        const row = element("div", "", `check-row ${check.passed === true ? "check-pass" : "check-fail"}`);
        row.append(element("span", check.passed === true ? "✓" : "✗", "check-icon"));
        const text = element("div", "", "check-text");
        text.append(element("strong", checkNames[name] || name));
        if (check.reason && check.passed !== true) text.append(element("p", check.reason, "prose"));
        row.append(text);
        grid.append(row);
      }
      wrap.append(grid);
    }
    if (summary.issues?.length) wrap.append(chips("提示", summary.issues));
    if (summary.adversarial_case) wrap.append(element("p", `反例检查：${summary.adversarial_case}`, "stage-footnote prose"));
    return wrap;
  }
  wrap.append(element("pre", JSON.stringify(summary, null, 2), "mini-json"));
  return wrap;
}

/* ---------- stage events ---------- */

function summaryLine(key, summary) {
  if (!summary) return "";
  if (summary.gaps) return `材料缺口：${summary.gaps[0]}`;
  if (key === "plan") return summary.topic ? `计划：${summary.topic}` : "";
  if (key === "author") return summary.stem ? `题面：${summary.stem.slice(0, 70)}${summary.stem.length > 70 ? "…" : ""}` : "";
  if (key === "reader") return summary.answer ? `独立答案：${summary.answer}` : "";
  if (key === "audit") return summary.valid === true ? "审计未发现阻断性问题。" : "审计发现阻断性问题。";
  return "";
}

function handleStageEvent(event) {
  const key = STAGE_BY_NAME[event.stage];
  if (!key) return;
  if (event.state === "start") {
    if (key === "plan") {
      if (run.stages.intake.state === "pending") setStage("intake", "passed", {elapsed: 0});
      if (run.stages.materials.state === "pending") setStage("materials", "passed", {elapsed: 0});
    }
    if (key === "reader" && run.stages.verify.state === "pending") {
      setStage("verify", "passed", {elapsed: 0});
    }
    setStage(key, "active");
    addLog(`开始 · ${event.stage}`, "info");
    setStatus("正在命题", "running", `当前阶段：${event.stage}。${stageFor(key).hint}。`);
  } else if (event.state === "ok") {
    run.calls += 1;
    if (event.tokens) {
      const count = (event.tokens.prompt_tokens || 0) + (event.tokens.completion_tokens || 0);
      run.tokens += count;
    }
    run.openStage = key;
    setStage(key, "passed", {
      elapsed: event.elapsed_seconds ?? null, tokens: event.tokens ?? null, summary: event.summary ?? null,
    });
    addLog(`通过 · ${event.stage}${event.elapsed_seconds != null ? ` · ${fmtDuration(event.elapsed_seconds)}` : ""}`, "success");
    const line = summaryLine(key, event.summary);
    if (line) addLog(line, "detail");
  } else if (event.state === "fail") {
    run.openStage = key;
    setStage(key, "failed", {
      elapsed: event.elapsed_seconds ?? null, error: event.error || "模型阶段没有完成。",
    });
    addLog(`阻断 · ${event.stage} · ${event.error || "模型阶段没有完成"}`, "error");
  }
}

/* ---------- final result ---------- */

function failureKey(result) {
  const report = result.authoring_report ?? {};
  const text = [report.stage, result.preview?.last_stage, result.message].filter(Boolean).join(" ");
  if (/定向取材|材料不足|材料未|缺少材料|知识库/.test(text)) return "materials";
  if (/需求细化|考查计划|计划/.test(text)) return "plan";
  if (/设计与结构|创作响应|结构检查/.test(text)) return "author";
  if (/独立|盲解|答案分歧|质量检查/.test(text)) return "reader";
  if (/反例|审计/.test(text)) return "audit";
  if (/缓存/.test(text)) return "delivery";
  if (result.status === "NEEDS_MATERIAL" || result.status === "KNOWLEDGE_BASE_UNAVAILABLE") return "materials";
  if (result.status === "MODEL_UNAVAILABLE") {
    const last = STAGE_BY_NAME[result.preview?.last_stage];
    return last ?? "plan";
  }
  if (result.status === "INVALID_REQUEST" || result.status === "CLOUD_CONFIRMATION_REQUIRED") return "intake";
  return "delivery";
}

function markSkippedAfter(index) {
  for (const stage of STAGES.slice(index + 1)) {
    if (run.stages[stage.key].state !== "failed") {
      run.stages[stage.key] = {...run.stages[stage.key], state: "skipped"};
    }
  }
}

function finishResult(result) {
  run.result = result;
  run.active = false;
  run.totalElapsed = run.clockStart ? (performance.now() - run.clockStart) / 1000 : null;
  stopClock();
  const preview = result.preview ?? {};
  run.calls = preview.calls ?? run.calls;
  if (Array.isArray(preview.usage)) {
    const total = preview.usage.reduce((sum, item) =>
      sum + (item.prompt_tokens || 0) + (item.completion_tokens || 0), 0);
    if (total) run.tokens = total;
    const elapsed = preview.usage.reduce((sum, item) => sum + (item.elapsed_seconds || 0), 0);
    if (elapsed) run.totalElapsed = elapsed;
  }
  byId("author-json").textContent = JSON.stringify(result, null, 2);
  byId("author-raw").hidden = false;

  if (result.status === "GENERATED") {
    const warnings = result.questions?.[0]?.self_check?.review_warnings;
    const soft = Array.isArray(warnings) && warnings.length > 0;
    for (const stage of STAGES) {
      if (run.stages[stage.key].state !== "passed") {
        run.stages[stage.key] = {...run.stages[stage.key], state: "passed"};
      }
    }
    blocked.hidden = true;
    setStatus(soft ? "生成完成 · 待审（含软警告）" : "生成完成 · 待审", soft ? "warning" : "success",
      soft ? "题包已通过自检，但反例审计留下了需要审校者留意的软警告。" : "题包通过命题自检，可展开查看答案与依据。");
    addLog(soft ? "交付完成，但带有软警告。" : "交付完成：题包已生成，等待独立审校。", soft ? "warn" : "success");
    renderQuestion(result.questions[0], false);
    byId("review-badge").hidden = false;
  } else {
    const key = failureKey(result);
    const index = STAGE_INDEX[key] ?? STAGES.length - 1;
    if (result.status !== "AUTHORING_CACHE_UNAVAILABLE") {
      for (const prior of STAGES.slice(0, index)) {
        if (run.stages[prior.key].state === "pending" || run.stages[prior.key].state === "active") {
          run.stages[prior.key] = {...run.stages[prior.key], state: "passed"};
        }
      }
    }
    const stage = stageFor(key);
    const reason = result.message || "本次没有生成可交付题目。";
    run.openStage = key;
    run.stages[key] = {...run.stages[key], state: "failed", error: reason};
    markSkippedAfter(index);
    blocked.hidden = false;
    byId("blocked-title").textContent = `阻断于「${stage.label}」`;
    byId("blocked-message").textContent = [result.authoring_report?.stage, reason].filter(Boolean).join(" · ");
    setStatus(failures[result.status] ?? result.status, "failure",
      `${stage.label}未通过。${reason}`);
    addLog(`未交付 · 阻断于 ${stage.label} · ${reason}`, "error");
    byId("review-badge").hidden = true;
    if (preview.unverified_draft) {
      renderQuestion(preview.unverified_draft, true);
      addLog("展示未通过验证的模型原始候选题面，仅供排查。", "warn");
    }
  }
  renderDiagnostics(result);
  updatePipeline();
  renderStages();
  tick();
}

function renderQuestion(question, draft) {
  const student = question.student_view;
  if (typeof student?.stem !== "string") return;
  const instructor = question.instructor_view;
  const meta = question.metadata ?? {};
  const parts = Array.isArray(student.parts) ? student.parts : [];
  const options = Array.isArray(student.options) ? student.options : [];
  byId("question-meta").textContent = draft ? "模型原始候选 · 未通过验证" : [
    subjectNames[meta.subject], typeNames[meta.question_type] || (parts.length ? "综合题" : "单选题"),
    meta.score && `${meta.score} 分`, meta.topic,
  ].filter(Boolean).join(" · ");
  byId("author-stem").textContent = student.stem;
  const partsNode = byId("author-parts");
  partsNode.type = parts.length ? "1" : "A";
  partsNode.replaceChildren(...(parts.length ? parts : options).map((part, index) => {
    const text = part?.prompt ? `${part.prompt}（${part.score} 分）` : part?.text ?? "";
    const item = element("li", text, "prose");
    if (!parts.length) item.dataset.option = "ABCD"[index] ?? String(index + 1);
    return item;
  }));
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
  byId("preview-empty").hidden = true;
}

function renderDiagnostics(result) {
  const question = result.questions?.[0];
  const report = result.authoring_report;
  const preview = result.preview;
  const plan = report?.plan ?? question?.generator?.parameters?.brief_plan ?? preview?.unverified_plan;
  const diagnostics = byId("author-diagnostics");
  diagnostics.replaceChildren();
  if (plan) {
    if (preview?.unverified_plan) diagnostics.append(element("p", "模型提出的计划 · 尚未通过验证", "stage-footnote"));
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
  if (Array.isArray(question?.self_check?.review_warnings) && question.self_check.review_warnings.length) {
    diagnostics.append(element("h3", "待审警告"));
    for (const warning of question.self_check.review_warnings) {
      diagnostics.append(element("p", `${warning.check}：${warning.reason}`, "prose review-warning"));
    }
  }
  if (report?.details) diagnostics.append(element("p", typeof report.details === "string"
    ? report.details : JSON.stringify(report.details, null, 2), "prose"));
  if (preview?.model) diagnostics.append(element("p", `${preview.model} · 本次调用 ${preview.calls ?? 0} 次`));
  byId("author-design").hidden = !diagnostics.childElementCount;
}

/* ---------- request transport ---------- */

function parseChunk(chunk) {
  for (const line of chunk.split("\n")) {
    if (!line.startsWith("data:")) continue;
    try {
      handleEvent(JSON.parse(line.slice(5).trim()));
    } catch {
      /* Ignore malformed keep-alive or partial frames. */
    }
  }
}

function handleEvent(event) {
  if (!event || typeof event !== "object") return;
  if (event.type === "stage") handleStageEvent(event);
  else if (event.type === "result") finishResult(event.result);
  else if (event.type === "error") {
    addLog(event.message || "命题过程出现未预期错误。", "error");
    if (!run.result) {
      blocked.hidden = false;
      byId("blocked-title").textContent = "命题过程异常中断";
      byId("blocked-message").textContent = event.message || "没有收到完整结果。";
      setStatus("请求失败", "failure", "没有收到完整结果。请检查试题台是否还在运行。");
    }
  }
}

async function consumeStream(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const {value, done} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {stream: true});
    let split;
    while ((split = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      parseChunk(chunk);
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) parseChunk(buffer);
}

async function requestResult(payload) {
  resetRun();
  controls.disabled = true;
  run.active = true;
  setStatus("正在命题", "running", "模块正在解析需求、取材、创作与自检。本机模型可能需要几分钟。");
  addLog("收到命题需求，开始解析。", "info");
  startClock();
  updatePipeline();
  renderStages();
  const body = JSON.stringify(payload);
  try {
    const response = await fetch("/api/author/stream", {
      method: "POST", headers: {"Content-Type": "application/json"}, body,
    });
    if (!response.ok || !response.body) throw new Error("stream unavailable");
    await consumeStream(response);
    if (!run.result) throw new Error("stream ended without result");
  } catch {
    addLog("实时进度连接中断，改用普通请求重试。", "warn");
    try {
      const response = await fetch("/api/author", {
        method: "POST", headers: {"Content-Type": "application/json"}, body,
      });
      const result = await response.json();
      finishResult(result);
    } catch {
      run.active = false;
      stopClock();
      setStatus("请求失败", "failure", "没有收到完整结果。请检查试题台是否还在运行。");
      addLog("请求失败：没有收到完整结果。", "error");
      blocked.hidden = false;
      byId("blocked-title").textContent = "无法连接试题台";
      byId("blocked-message").textContent = "请确认本地试题台仍在运行，然后重试。";
    }
  } finally {
    run.active = false;
    controls.disabled = false;
    updatePipeline();
    stopClock();
  }
}

async function loadHistory() {
  resetRun();
  controls.disabled = true;
  run.active = true;
  run.history = true;
  setStatus("正在载入", "running", "正在读取已保存的历史题包。");
  addLog("载入历史实测题包，本次没有重新调用模型。", "info");
  startClock();
  try {
    const response = await fetch("/api/history-example");
    const result = await response.json();
    for (const stage of STAGES) run.stages[stage.key] = {...run.stages[stage.key], state: "passed"};
    finishResult(result);
    addLog("历史题包已载入，仅用于回看，不代表本次生成。", "warn");
  } catch {
    run.active = false;
    setStatus("载入失败", "failure", "无法读取历史题包，请刷新页面后重试。");
  } finally {
    controls.disabled = false;
    run.active = false;
    updatePipeline();
    stopClock();
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
  if (excerpt) {
    request.evidence = [{id: "user-material", source: fields.get("source").trim() || "用户提供",
      version: "本次提交", anchor: "粘贴原文", summary: excerpt.slice(0, 360), excerpt, rules: []}];
  }
  const confirmed = byId("cloud-confirmed").checked;
  byId("cloud-confirmed").checked = false;
  await requestResult({request, cloud_confirmed: confirmed});
});

for (const button of form.querySelectorAll("[data-brief]")) {
  button.addEventListener("click", () => {
    byId("brief").value = button.dataset.brief;
    byId("brief").focus();
  });
}

byId("history-example").addEventListener("click", loadHistory);

async function initialize() {
  buildPipeline();
  resetRun();
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
    setStatus("等待输入", "idle", "提交需求后，这里会逐段点亮线路，并保留每个阶段的输出与日志。");
  } catch {
    setStatus("连接失败", "failure", "试题台配置暂不可读，请刷新页面。");
    addLog("无法读取试题台配置。", "error");
  }
}

initialize();
