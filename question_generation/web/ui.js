"use strict";

const byId = (id) => document.getElementById(id);
const form = byId("request-form");
const controls = byId("controls");
const ruleInputs = () => Array.from(form.querySelectorAll('[name="rule"]'));
const field = (name) => form.elements.namedItem(name);
const status = byId("status");
const message = byId("message");
const ruleNames = {
  split_address: "拆分虚页号与偏移",
  map_virtual_page: "查有效页表项",
  preserve_offset: "保留页内偏移",
  stack_push_top: "从栈顶入栈",
  stack_pop_top: "从栈顶出栈",
};
const examples = {};
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
  if (field("topic").value === "stack") {
    field("element_count").value = {boundary: 4, invalid: 3}[preset] ?? example.constraints.element_count;
  } else {
    field("page_size").value = preset === "invalid" ? 300 : example.constraints.page_size;
    field("offset").value = preset === "boundary" ? 0 : "";
  }
  const inputs = ruleInputs();
  for (const [index, input] of inputs.entries()) {
    input.checked = preset !== "missing" || index !== inputs.length - 1;
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
  let constraints;
  if (field("topic").value === "stack") {
    constraints = {element_count: field("element_count").valueAsNumber};
  } else {
    constraints = {page_size: field("page_size").valueAsNumber};
    if (field("offset").value !== "") {
      constraints.offset = field("offset").valueAsNumber;
    }
  }
  const rules = ruleInputs().filter((input) => input.checked).map((input) => input.value);
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
  const topic = field("topic").value;
  controls.disabled = true;
  resetResult();
  setStatus("载入样例中", "idle");
  try {
    if (!examples[topic]) {
      const response = await fetch(topic === "stack" ? "/api/example/stack" : "/api/example");
      if (!response.ok) throw new Error("Example unavailable");
      examples[topic] = await response.json();
    }
    example = examples[topic];
    const isStack = topic === "stack";
    byId("paging-fields").hidden = byId("paging-fields").disabled = isStack;
    byId("stack-fields").hidden = byId("stack-fields").disabled = !isStack;
    form.querySelector('[data-preset="boundary"]').textContent = isStack ? "最少元素" : "零偏移";
    form.querySelector('[data-preset="invalid"]').textContent = isStack ? "非法元素个数" : "非法页大小";
    byId("material-rules").replaceChildren(...example.evidence[0].rules.map((rule) => {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.name = "rule";
      input.value = rule;
      label.append(input, ` ${ruleNames[rule]}`);
      return label;
    }));
    applyPreset("standard");
    byId("material-summary").textContent = `${example.evidence[0].version} · ${example.evidence[0].anchor}`;
    controls.disabled = false;
    setStatus("等待生成", "idle");
    message.textContent = "选择预设或调整参数后生成。";
  } catch {
    setStatus("无法载入样例", "failure");
    message.textContent = "请确认本地验证台正在运行，然后刷新页面。";
  }
}

field("topic").addEventListener("change", loadExample);
loadExample();
