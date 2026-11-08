"use strict";

const byId = (id) => document.getElementById(id);
const form = byId("request-form");
const controls = byId("controls");
const ruleInputs = Array.from(form.querySelectorAll('[name="rule"]'));
const field = (name) => form.elements.namedItem(name);
const status = byId("status");
const message = byId("message");
const ruleNames = {
  split_address: "拆分虚页号与偏移",
  map_virtual_page: "查有效页表项",
  preserve_offset: "保留页内偏移",
};
let example;

function setStatus(text, tone) {
  status.textContent = text;
  status.dataset.tone = tone;
}

function resetResult() {
  byId("question").hidden = true;
  byId("raw-details").hidden = true;
  for (const id of ["teacher", "verification", "raw-details"]) {
    byId(id).open = false;
  }
}

function setItems(id, texts) {
  byId(id).replaceChildren(...texts.map((text) => {
    const item = document.createElement("li");
    item.textContent = text;
    return item;
  }));
}

function applyPreset(preset) {
  field("seed").value = example.seed;
  field("page_size").value = preset === "invalid" ? 300 : example.constraints.page_size;
  field("offset").value = preset === "zero" ? 0 : "";
  for (const input of ruleInputs) {
    input.checked = example.evidence[0].rules.includes(input.value)
      && !(preset === "missing" && input.value === "preserve_offset");
  }
}

function showResult(result) {
  byId("raw").textContent = JSON.stringify(result, null, 2);
  byId("raw-details").hidden = false;
  if (result.status !== "GENERATED") {
    setStatus(result.status, "failure");
    const missing = (result.missing_rules ?? []).map((rule) => ruleNames[rule] ?? rule);
    message.textContent = missing.length ? `${result.message} 缺少：${missing.join("、")}。` : result.message;
    return;
  }

  const [question] = result.questions;
  const {student_view: student, instructor_view: instructor} = question;
  setStatus("已生成 · 自检通过", "success");
  message.textContent = `题目 ${question.question_id} · 待独立审校`;
  byId("stem").textContent = student.stem;
  setItems("options", student.options.map((option) => option.text));

  const answerIndex = student.options.findIndex((option) => option.id === instructor.correct_option_id);
  byId("solution").textContent = `答案 ${"ABCD"[answerIndex]} · ${instructor.explanation}`;
  setItems("explanations", student.options.map((option, index) =>
    `${"ABCD"[index]}. ${option.text} · ${instructor.option_explanations[option.id]}`
  ));
  byId("checks").textContent = "四个不同选项 · 独立复算答案一致";
  setItems("references", question.evidence_refs.map((ref) =>
    `${ref.version} · ${ref.anchor} · ${ref.source}`
  ));
  byId("parameters").textContent = JSON.stringify(question.generator, null, 2);
  byId("question").hidden = false;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const constraints = {page_size: field("page_size").valueAsNumber};
  if (field("offset").value !== "") {
    constraints.offset = field("offset").valueAsNumber;
  }
  const rules = ruleInputs.filter((input) => input.checked).map((input) => input.value);
  const payload = {
    ...example,
    seed: field("seed").valueAsNumber,
    constraints,
    evidence: [{...example.evidence[0], rules}],
  };
  controls.disabled = true;
  resetResult();
  setStatus("正在生成", "idle");
  message.textContent = "正在运行本地命题模块。";
  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    showResult(await response.json());
  } catch {
    setStatus("请求失败", "failure");
    message.textContent = "无法获取验证结果。请确认本地验证台仍在运行，然后重试。";
    resetResult();
  } finally {
    controls.disabled = false;
  }
});

for (const button of form.querySelectorAll("[data-preset]")) {
  button.addEventListener("click", () => {
    applyPreset(button.dataset.preset);
    form.requestSubmit();
  });
}

async function loadExample() {
  try {
    const response = await fetch("/api/example");
    if (!response.ok) throw new Error("Example unavailable");
    example = await response.json();
    applyPreset("standard");
    byId("material-summary").textContent = `${example.evidence[0].version} · ${example.evidence[0].anchor}`;
    controls.disabled = false;
    setStatus("等待生成", "idle");
  } catch {
    setStatus("无法载入样例", "failure");
    message.textContent = "请确认本地验证台正在运行，然后刷新页面。";
  }
}

loadExample();
