"use client";

import { useAui } from "@assistant-ui/react";
import { BookOpen, Database, FileText, History, Home as HomeIcon, Menu, PenLine, RefreshCw } from "lucide-react";
import Image from "next/image";
import { useCallback, useEffect, useState } from "react";
import { AssemblyForm, HistoryDetail, HistoryList } from "@/components/assembly-workspace";
import { PiRequests } from "@/components/pi-requests";
import { QodexThread } from "@/components/qodex-thread";
import { QodexThreadList } from "@/components/qodex-thread-list";
import { CheckerWorkspace, QuestionBank } from "@/components/question-workspace";
import { RuntimeStatus } from "@/components/runtime-status";
import { api, type JsonObject, text } from "@/lib/workspace-api";
import { QodexRuntimeProvider } from "./runtime-provider";

export default function Home() {
	return (
		<QodexRuntimeProvider>
			<Workspace />
			<PiRequests />
		</QodexRuntimeProvider>
	);
}
function Workspace() {
	const aui = useAui();
	const [route, setRoute] = useState("chat"),
		[sidebarOpen, setSidebarOpen] = useState(true),
		[health, setHealth] = useState<JsonObject>({}),
		[checking, setChecking] = useState(false);
	const pages = [
		["chat", "工作台", HomeIcon],
		["checker", "命题与审校", PenLine],
		["bank", "正式题库", Database],
		["assembly", "智能组卷", FileText],
		["history", "组卷历史", History],
	] as const;
	useEffect(() => {
		const update = () => setRoute(location.hash.slice(1) || "chat");
		update();
		window.addEventListener("hashchange", update);
		return () => window.removeEventListener("hashchange", update);
	}, []);
	const checkHealth = useCallback(async () => {
		setChecking(true);
		const states = await Promise.all(
			["checker", "assembly", "generation"].map(async (s) => {
				try {
					const result = await api(`${s}/health`);
					return [s, result.status === "ok" ? "已连接" : "异常"];
				} catch {
					return [s, "未连接"];
				}
			}),
		);
		setHealth(Object.fromEntries(states));
		setChecking(false);
	}, []);
	useEffect(() => {
		void checkHealth();
	}, [checkHealth]);
	function prompt(value: string) {
		location.hash = "chat";
		aui.composer.setText(value);
	}
	function openHistory(id?: string) {
		location.hash = id ? `exam/${id}` : "history";
	}
	const detailId = route.startsWith("exam/") ? route.slice(5) : "";
	const title = detailId ? "试卷详情" : pages.find((p) => p[0] === route)?.[1] || "工作台";
	return (
		<div className="qx-app">
			<aside className={`qx-sidebar ${sidebarOpen ? "is-open" : ""}`}>
				<a className="qx-brand" href="#chat">
					<Image src="/qodex-logo.svg" width="43" height="43" alt="Qodex" />
					<div>
						<strong>Qodex</strong>
						<small>QUESTION · CODEX</small>
					</div>
				</a>
				<nav className="qx-nav" aria-label="主导航">
					{pages.map(([key, label, Icon]) => (
						<a
							key={key}
							href={`#${key}`}
							className={route === key || (key === "history" && !!detailId) ? "active" : ""}
						>
							<Icon size={18} />
							{label}
						</a>
					))}
				</nav>
				<div className="qx-chatlist">
					<QodexThreadList />
				</div>
				<div className="qx-sidefooter">
					<BookOpen size={16} />
					<div>
						本地教师工作区<small>计算机考研 · 408</small>
					</div>
				</div>
			</aside>
			<section className="qx-main">
				<header className="qx-topbar">
					<button
						type="button"
						className="qx-iconbtn"
						aria-label="切换侧边栏"
						onClick={() => setSidebarOpen((v) => !v)}
					>
						<Menu size={18} />
					</button>
					<span className="qx-crumb">
						教师工作台 <span>/</span> <b>{title}</b>
					</span>
					<div className="qx-health">
						<details>
							<summary>
								业务服务{" "}
								{Object.keys(health).length === 0
									? "检查中"
									: Object.values(health).every((v) => v === "已连接")
										? "已连接"
										: "需检查"}
							</summary>
							<div className="qx-healthmenu">
								{[
									["checker", "审校 / 题库"],
									["assembly", "组卷 / 历史"],
									["generation", "自主命题"],
								].map(([k, v]) => (
									<p key={k}>
										{v}
										<span>{text(health[k]) || "检查中"}</span>
									</p>
								))}
								<button type="button" className="qx-link" disabled={checking} onClick={checkHealth}>
									<RefreshCw size={13} />
									重新检查
								</button>
							</div>
						</details>
						<RuntimeStatus />
					</div>
				</header>
				<main className="qx-mainbody">
					<div
						className={
							route === "chat" || (!["checker", "bank", "assembly", "history"].includes(route) && !detailId)
								? "qx-chatpanel"
								: "qx-hidden"
						}
					>
						<QodexThread />
					</div>
					<div className={route === "assembly" ? "qx-scrollpanel" : "qx-hidden"}>
						<AssemblyForm openHistory={openHistory} />
					</div>
					<div className={route === "checker" ? "qx-scrollpanel" : "qx-hidden"}>
						<CheckerWorkspace prompt={prompt} />
					</div>
					<div className={route === "bank" ? "qx-scrollpanel" : "qx-hidden"}>
						<QuestionBank />
					</div>
					{route === "history" && (
						<div className="qx-scrollpanel">
							<HistoryList active open={openHistory} />
						</div>
					)}
					{detailId && (
						<div className="qx-scrollpanel">
							<HistoryDetail id={detailId} />
						</div>
					)}
				</main>
			</section>
		</div>
	);
}
