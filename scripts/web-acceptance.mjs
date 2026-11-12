/** Explicit local acceptance run: one real assembly and one deterministic pending question. */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const base = process.env.QODEX_WEB_URL || "http://127.0.0.1:3100";
const readOnly = process.argv.includes("--read-only");
const output = join(root, readOnly ? ".local/web-readonly-acceptance" : ".local/web-acceptance");
mkdirSync(output, { recursive: true });
if (existsSync(join(output, "result.json"))) throw Error("Acceptance result already exists. Preserve it; choose a new output directory before deliberately running mutations again.");
const results = { checks: {}, errors: [], examId: "" };
async function request(path, options) {
	const response = await fetch(`${base}/api/services/${path}`, options);
	const data = await response.json();
	assert.equal(response.status, 200, JSON.stringify(data));
	return data;
}
for (const s of ["checker", "assembly", "generation"]) {
	const data = await request(`${s}/health`);
	assert.equal(data.status, "ok");
	results.checks[`${s}Health`] = true;
}
const bank = await request("checker/v1/question-bank/search?limit=100");
results.checks.realBank = bank.questions.length > 0;
assert.ok(results.checks.realBank, "An accepted question bank is required; no mock bank is used.");
const histories = await request("assembly/v1/exam-assembly/history?limit=20");
results.checks.historyList = Array.isArray(histories.exams);
const hostile = await fetch(`${base}/api/services/assembly/health`, { headers: { origin: "https://evil.example" } });
assert.equal(hostile.status, 403);results.checks.originGuard = true;
const browserPath = process.env.QODEX_BROWSER || ["C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].find(existsSync);
if (!browserPath) throw Error("Set QODEX_BROWSER to an installed Chromium browser.");
const child = spawn(browserPath, ["--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars", "--remote-debugging-port=9457", `--user-data-dir=${join(output, "browser")}`, "about:blank"], { windowsHide: true, stdio: "ignore" });
let ws;
try {
	let tabs;
	for (let i=0;i<60;i++) { try { tabs=await(await fetch("http://127.0.0.1:9457/json")).json();break; } catch { await new Promise(r=>setTimeout(r,200)); } }
	assert.ok(tabs,"Browser could not start");
	ws=new WebSocket(tabs.find(t=>t.type==="page").webSocketDebuggerUrl);
	await new Promise((resolve,reject)=>{ws.addEventListener("open",resolve,{once:true});ws.addEventListener("error",reject,{once:true});});
	let seq=0;const pending=new Map();
	ws.addEventListener("message",event=>{const m=JSON.parse(event.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);if(m.error)p.reject(Error(m.error.message));else p.resolve(m.result);}if(m.method==="Runtime.exceptionThrown")results.errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);});
	const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));setTimeout(()=>{if(pending.has(id)){pending.delete(id);reject(Error(`CDP timeout: ${method}`));}},30000).unref();});
	const evaluate=async expression=>{const r=await call("Runtime.evaluate",{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||"Evaluation failed");return r.result.value;};
	async function until(expression,seconds=90){for(let i=0;i<seconds*4;i++){if(await evaluate(expression))return;await new Promise(r=>setTimeout(r,250));}throw Error(`UI condition timed out: ${expression}`);}
	async function shot(name){const r=await call("Page.captureScreenshot",{format:"png",captureBeyondViewport:false});writeFileSync(join(output,`${name}.png`),Buffer.from(r.data,"base64"));}
	await call("Page.enable");await call("Runtime.enable");await call("Emulation.setDeviceMetricsOverride",{width:1500,height:1000,deviceScaleFactor:1,mobile:false});
	await call("Page.navigate",{url:base});await until("document.querySelector('.qx-health summary')?.textContent.includes('已连接')");await evaluate("document.fonts.ready.then(()=>true)");await shot("01-workspace");
	await evaluate("document.querySelector('.qx-nav a[href=\"#bank\"]').click();true");await until("!!document.querySelector('.qx-scrollpanel button[type=submit]')");
	await evaluate("document.querySelector('.qx-scrollpanel button[type=submit]').click();true");await until("document.querySelectorAll('.qx-bankitem').length>0");results.checks.bankUI=true;await shot("02-real-bank");
	await evaluate("location.hash='assembly';true");await until("[...document.querySelectorAll('.qx-scrollpanel button')].some(b=>b.textContent==='开始组卷')");await shot("03-assembly-form");
	if(readOnly){const previous=histories.exams.find(e=>e.status==="STRUCTURAL_PASS"&&e.requested_question_count===3);assert.ok(previous);await evaluate(`location.hash='exam/${previous.exam_id}';true`);}else{await evaluate("[...document.querySelectorAll('.qx-scrollpanel button')].find(b=>b.textContent==='开始组卷').click();true");}
	await until("location.hash.startsWith('#exam/')",120);
	results.examId=await evaluate("location.hash.slice(6)");
	const detail=await request(`assembly/v1/exam-assembly/history/${results.examId}`);
	assert.equal(detail.status,"STRUCTURAL_PASS");assert.equal(detail.student_exam.length,3);assert.equal(detail.answer_key,undefined);
	results.checks.realAssemblySnapshot=true;await until("!!document.querySelector('iframe')");await new Promise(r=>setTimeout(r,500));await shot("04-real-exam");
	const answers=await request(`assembly/v1/exam-assembly/history/${results.examId}/answers`);assert.equal(answers.answer_key.length,3);results.checks.separateAnswers=true;
	const studentHtml=await fetch(`${base}/api/services/assembly/v1/exam-assembly/history/${results.examId}/student.html`);assert.equal(studentHtml.status,200);assert.match(studentHtml.headers.get("content-security-policy"),/sandbox/);results.checks.snapshotHtml=true;
	await evaluate("[...document.querySelectorAll('.qx-previewbar button')].find(b=>b.textContent.includes('答案与解析')).click();true");await until("document.querySelector('iframe').src.includes('answer.html')");await new Promise(r=>setTimeout(r,350));await shot("05-real-answers");
	await evaluate("location.hash='history';true");await until("document.querySelectorAll('.qx-table tbody tr').length>0");await shot("06-real-history");results.checks.historyUI=true;
	await call("Emulation.setDeviceMetricsOverride",{width:900,height:850,deviceScaleFactor:1,mobile:false});await new Promise(r=>setTimeout(r,200));results.checks.noHorizontalOverflow=await evaluate("document.body.scrollWidth<=innerWidth");assert.ok(results.checks.noHorizontalOverflow);
	await evaluate("location.hash='checker';true");await until("!!document.querySelector('input[type=file]')");results.checks.checkerUploadUI=true;
	assert.deepEqual(results.errors,[]);
	if(!readOnly){
	const sample=JSON.parse(readFileSync(join(root,"question_generation/examples/paging.json"),"utf8"));sample.request_id=`web-acceptance-${Date.now()}`;
	const generated=await request("generation/v1/question-generation/single",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(sample)});
	assert.ok(generated.queue_receipts?.length>0);results.checks.deterministicGenerationQueued=true;
	const excessive={...detail.request,request_id:`web-shortage-${Date.now()}`,question_count:100,total_score:200,question_type_counts:{single_choice:100},question_type_scores:{single_choice:2},knowledge_point_counts:{"线性表顺序存储":100},difficulty_counts:{easy:100,medium:0,hard:0}};
	const shortage=await request("assembly/v1/exam-assembly/assemble",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(excessive)});assert.equal(shortage.status,"NEEDS_QUESTIONS");assert.equal(shortage.history.status,"STORED");results.checks.shortageStored=true;
	const noExam=await fetch(`${base}/api/services/assembly/v1/exam-assembly/history/${shortage.history.exam_id}/student.html`);assert.equal(noExam.status,409);results.checks.noIncompleteDownload=true;
	}
	writeFileSync(join(output,"result.json"),JSON.stringify(results,null,2));console.log(JSON.stringify(results,null,2));await call("Browser.close");
} finally {ws?.close();child.kill();}
