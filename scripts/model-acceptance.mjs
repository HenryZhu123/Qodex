// Explicit live acceptance. Uses configured local services and a small amount of model credit.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root=resolve(dirname(fileURLToPath(import.meta.url)),"..");
const out=join(root,".local",process.env.QODEX_MODEL_TEST_NAME||"model-acceptance");mkdirSync(out,{recursive:true});
const base=process.env.QODEX_WEB_URL||"http://127.0.0.1:3000";
const phase=process.argv[2]||"pi";
const resultFile=join(out,`${phase}.json`);
if(existsSync(resultFile))throw Error("This phase already has a result; inspect it before repeating paid requests.");
async function api(path,body){
	const r=await fetch(base+path,{method:body===undefined?"GET":"POST",headers:body===undefined?{}:{"content-type":"application/json"},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(600000)});
	const data=r.status===204?null:await r.json();if(!r.ok){writeFileSync(join(out,`${phase}-error.json`),JSON.stringify({status:r.status,detail:data},null,2));throw Error(`${phase}: HTTP ${r.status}; see ignored local diagnostic file`);}return data;
}
if(phase==="pi"){
	const checkpoint=join(out,"pi-thread.json");
	const resume=existsSync(checkpoint);
	const created=resume?await api(`/api/pi/threads/${JSON.parse(readFileSync(checkpoint,"utf8")).id}`):await api("/api/pi/threads",{title:"本地验收 · 只读题库查询"});const id=created.metadata.id;
	writeFileSync(join(out,"pi-thread.json"),JSON.stringify({id},null,2));
	assert.equal(created.readiness?.state,"ready",`Pi model not ready: ${created.readiness?.state}`);
	console.log("Pi model ready; requesting one read-only bank tool call.");
	if(!resume)await api(`/api/pi/threads/${id}/messages`,{input:{content:"本次是本地接口验收。请仅调用一次 question_bank，operation=search_questions，limit=1。不调用其他工具，不修改文件、不命题、不审校、不组卷。根据工具实际结果，用一句中文报告返回题数。"}});
	let snapshot;
	for(let i=0;i<180;i++){
		snapshot=await api(`/api/pi/threads/${id}`);
		if(snapshot.lastError)throw Error("Pi reported an error; inspect this local test thread.");
		if(snapshot.metadata.status!=="running"&&snapshot.messages.length>1)break;
		await new Promise(r=>setTimeout(r,1000));
	}
	writeFileSync(join(out,"pi-snapshot.json"),JSON.stringify(snapshot,null,2));
	const wire=JSON.stringify(snapshot.messages);
	assert.ok(wire.includes("question_bank"),"No actual bank tool call observed");
	assert.ok(wire.includes("toolResult")||wire.includes("tool-result"),"No tool result observed");
	const result={thread_id:id,status:snapshot.metadata.status,model:snapshot.metadata.config,observed_bank_tool:true,verified: true};
	writeFileSync(resultFile,JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
}else if(phase==="parse"){
	const file=process.argv[3];if(!file)throw Error("Pass an existing small PDF filename.");
	const form=new FormData();form.append("file",new Blob([readFileSync(file)],{type:"application/pdf"}),"qodex_checker_smoke_test.pdf");
	console.log("Uploading one small PDF through the frontend proxy; no automatic retry.");
	const r=await fetch(base+"/api/services/checker/v1/exam-checker/documents/parse",{method:"POST",headers:{origin:base},body:form,signal:AbortSignal.timeout(600000)});
	const data=await r.json();writeFileSync(join(out,"parsed-document.json"),JSON.stringify(data,null,2));
	assert.equal(r.status,200,`Parse failed: HTTP ${r.status}; inspect parsed-document.json`);
	const questions=Object.values(data.nodes).filter(n=>n.type==="question");assert.ok(questions.length>0);
	const result={document_id:data.document_id,question_ids:questions.map(q=>q.id),question_count:questions.length};writeFileSync(resultFile,JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
}else if(phase==="review"){
	const parsed=JSON.parse(readFileSync(join(out,"parse.json"),"utf8"));const id=parsed.question_ids[0];
	console.log("Reviewing only the first parsed test question, using the real configured review service.");
	const path=`/api/services/checker/v1/exam-checker/documents/${parsed.document_id}/questions/${id}`;
	const data=await api(path+"/review",{});writeFileSync(join(out,"review-detail.json"),JSON.stringify(data,null,2));
	const state=await api(path+"/state");
	const checks=data.review?.checks||[];
	const result={document_id:parsed.document_id,question_id:id,status:data.review?.status,checks:checks.map(c=>({task_id:c.task_id,status:c.execution_status,kb_queries:c.kb_queries})),unresolved_checks:data.review?.summary?.unresolved_checks,ingestion:data.ingestion,stored_state:state.question_bank};
	writeFileSync(resultFile,JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
	assert.ok(["PASS","NEEDS_REVISION","UNRESOLVED"].includes(result.status));
	assert.ok(checks.some(c=>c.execution_status==="COMPLETED"),"No specialist check completed");
}else if(phase==="revise"){
	const parsed=JSON.parse(readFileSync(join(out,"parse.json"),"utf8"));
	const path=`/api/services/checker/v1/exam-checker/documents/${parsed.document_id}/questions/${parsed.question_ids[0]}`;
	const state=await api(path+"/state");
	assert.equal(state.review.status,"NEEDS_REVISION");
	const question={...state.question,question_text:state.question.question_text.replace("pop(、","pop()、"),options:["A. 1","B. 2","C. 3","D. 栈为空"]};
	assert.equal(question.answer_text,"C","Do not invent a missing source answer");
	const data=await api(path+"/revise",{base_version_id:state.question_version_id,question_json:question,user_instruction:"这是自行编写测试卷的原文还原。仅修正审校指出的 pop() 右括号和选项标签后的空格；保持题意、标准答案 C、来源标识及分值不变，不引入新题。"});
	writeFileSync(join(out,"revision-detail.json"),JSON.stringify(data,null,2));
	const latest=await api(path+"/state");
	const result={document_id:parsed.document_id,question_id:parsed.question_ids[0],status:data.review.status,ingestion:data.ingestion,version_number:latest.version_number,question_version_id:latest.question_version_id};
	writeFileSync(resultFile,JSON.stringify(result,null,2));
	assert.equal(result.status,"PASS");assert.equal(result.ingestion?.status,"STORED");
	console.log(JSON.stringify(result,null,2));
}else if(phase==="assemble"){
	const review=JSON.parse(readFileSync(join(out,existsSync(join(out,"revise.json"))?"revise.json":"review.json"),"utf8"));
	assert.equal(review.ingestion?.status,"STORED");
	const entry=await api(`/api/services/checker/v1/question-bank/${review.ingestion.record_id}`);
	const q=entry.question_json.question, meta=entry.question_json.metadata;
	const data=await api("/api/services/assembly/v1/exam-assembly/assemble",{
		schema_version:"1.0",request_id:`PDF解析审校入库联调-${Date.now()}`,subject:q.subject,
		question_count:1,total_score:q.points,question_type_counts:{single_choice:1},question_type_scores:{single_choice:q.points},
		knowledge_point_counts:{[meta.knowledge_points[0]]:1},difficulty_counts:{easy:0,medium:0,hard:0,[meta.difficulty]:1},export_pdf:false,
	});
	writeFileSync(join(out,"assembly-response.json"),JSON.stringify(data,null,2));
	assert.equal(data.status,"STRUCTURAL_PASS");assert.equal(data.history.status,"STORED");
	assert.ok(data.selected_sources.some(source=>source.record_id===entry.record_id),"The newly reviewed question was not selected");
	const detail=await api(`/api/services/assembly/v1/exam-assembly/history/${data.history.exam_id}`);
	assert.equal(detail.student_exam.length,1);
	const result={status:data.status,exam_id:data.history.exam_id,source_record_id:entry.record_id,document_id:review.document_id,verified_entire_chain:true};
	writeFileSync(resultFile,JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
}else{throw Error("Unknown phase");}
