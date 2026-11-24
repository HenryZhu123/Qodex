"use client";

import {
	ActionBarPrimitive,
	AuiIf,
	ComposerPrimitive,
	ErrorPrimitive,
	groupPartByType,
	MessagePartPrimitive,
	MessagePrimitive,
	QueueItemPrimitive,
	ThreadPrimitive,
	type ToolCallMessagePartComponent,
	useAui,
	useAuiState,
} from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import { type PiModelInfo, usePiRuntimeExtras, usePiThreadState } from "@assistant-ui/react-pi";
import {
	ArrowDownIcon,
	ArrowUpIcon,
	CheckIcon,
	ChevronDownIcon,
	CopyIcon,
	MicIcon,
	PlusIcon,
	SparklesIcon,
	SquareIcon,
	Trash2Icon,
	WrenchIcon,
} from "lucide-react";
import Image from "next/image";
import { type ReactNode, useEffect, useRef, useState } from "react";
import type { BuildJob } from "@/lib/kb-store";
import { parseModelSelection } from "@/lib/workspace-api";

const SUGGESTIONS = [
	"查询已审校题库中的数据结构题目",
	"先和我确认需求，再帮我智能组卷",
	"介绍单题、批量和综合题的命题功能",
	"告诉我怎样审校试卷和修订题目",
];
const KB_SKILL_COMMAND = "/skill:build-knowledge-base";

export function QodexThread() {
	const readiness = usePiThreadState((state) => state.readiness);
	const lastError = usePiThreadState((state) => state.lastError);
	const isEmpty = useAuiState((state) => state.thread.isEmpty);

	return (
		<ThreadPrimitive.Root className="flex h-full min-h-0 flex-col">
			{readiness && readiness.state !== "ready" ? (
				<div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
					{readiness.message ?? "Configure a Pi model and credentials before sending."}
				</div>
			) : null}
			{lastError ? (
				<div className="border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{lastError}</div>
			) : null}

			<ThreadPrimitive.Viewport className="relative flex min-h-0 flex-1 flex-col overflow-y-auto scroll-smooth">
				{isEmpty ? (
					<div className="mx-auto flex min-h-full w-full max-w-[840px] flex-1 flex-col items-center justify-center px-4 py-12 sm:px-6">
						<Welcome />
						<div className="mt-8 w-full">
							<ComposerArea showSuggestions />
						</div>
					</div>
				) : (
					<div className="mx-auto flex w-full max-w-[860px] flex-1 flex-col px-4 pt-8 sm:px-6">
						<div className="flex flex-col gap-8 pb-8">
							<ThreadPrimitive.Messages>{() => <ThreadMessage />}</ThreadPrimitive.Messages>
						</div>
						<ThreadPrimitive.ViewportFooter className="sticky bottom-0 mt-auto bg-white pb-5 pt-3">
							<ThreadPrimitive.ScrollToBottom className="absolute -top-1 left-1/2 flex size-8 -translate-x-1/2 items-center justify-center rounded-full border border-[var(--border)] bg-white text-[var(--muted)] shadow-sm transition hover:text-[var(--text)] disabled:invisible">
								<ArrowDownIcon className="size-4" />
								<span className="sr-only">Scroll to bottom</span>
							</ThreadPrimitive.ScrollToBottom>
							<ComposerArea />
						</ThreadPrimitive.ViewportFooter>
					</div>
				)}
			</ThreadPrimitive.Viewport>
		</ThreadPrimitive.Root>
	);
}

function Welcome() {
	return (
		<div className="text-center">
			<div className="mx-auto mb-5 flex size-10 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--panel-subtle)] text-[var(--text)] shadow-sm">
				<Image src="/qodex-logo.svg" width="58" height="58" alt="Qodex" />
			</div>
			<h1 className="m-0 text-[32px] font-semibold tracking-[-0.045em] text-[var(--text)] sm:text-[36px]">
				把好题，组成一份好试卷。
			</h1>
			<p className="mx-auto mt-3 max-w-lg text-sm leading-6 text-[var(--muted)]">
				从命题、审校到组卷，让每一次教学准备更从容。左侧可直接配置组卷与查看历史。
			</p>
		</div>
	);
}

function ThreadMessage() {
	const role = useAuiState((state) => state.message.role);
	return role === "user" ? <UserMessage /> : <AssistantMessage />;
}

function UserMessage() {
	return (
		<MessagePrimitive.Root className="ml-auto max-w-[82%]">
			<div className="rounded-[18px] rounded-br-md bg-[var(--panel-subtle)] px-4 py-2.5 text-sm leading-6 text-[var(--text)]">
				<MessagePrimitive.Parts />
			</div>
		</MessagePrimitive.Root>
	);
}

function AssistantMessage() {
	return (
		<MessagePrimitive.Root className="group relative min-w-0 text-sm leading-7 text-[var(--text)]">
			<MessagePrimitive.GroupedParts
				groupBy={groupPartByType({
					reasoning: ["group-work", "group-reasoning"],
					"tool-call": ["group-work", "group-tools"],
					"standalone-tool-call": [],
				})}
			>
				{({ part, children }) => {
					switch (part.type) {
						case "group-work":
							return (
								<div className="mb-4 overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--panel-subtle)]">
									{children}
								</div>
							);
						case "group-reasoning":
							return (
								<Disclosure label="Reasoning" running={part.status.type === "running"}>
									{children}
								</Disclosure>
							);
						case "group-tools":
							return (
								<Disclosure
									label={`${part.indices.length} tool${part.indices.length === 1 ? "" : "s"}`}
									running={part.status.type === "running"}
								>
									{children}
								</Disclosure>
							);
						case "text":
							return <MarkdownTextPrimitive className="qodex-markdown" />;
						case "reasoning":
							return <MessagePartPrimitive.Text className="block whitespace-pre-wrap text-[var(--muted)]" />;
						case "tool-call":
							return part.toolUI ?? <ToolFallback {...part} />;
						case "indicator":
							return <span className="qodex-pulse text-[var(--muted)]">●</span>;
						default:
							return null;
					}
				}}
			</MessagePrimitive.GroupedParts>
			<MessagePrimitive.Error>
				<ErrorPrimitive.Root className="mt-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-red-700">
					<ErrorPrimitive.Message />
				</ErrorPrimitive.Root>
			</MessagePrimitive.Error>
			<ActionBarPrimitive.Root
				hideWhenRunning
				autohide="not-last"
				className="mt-1 flex h-7 items-center opacity-0 transition group-hover:opacity-100"
			>
				<ActionBarPrimitive.Copy className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-[var(--muted)] hover:bg-[var(--hover)] hover:text-[var(--text)]">
					<AuiIf condition={(state) => state.message.isCopied}>
						<CheckIcon className="size-3.5" />
					</AuiIf>
					<AuiIf condition={(state) => !state.message.isCopied}>
						<CopyIcon className="size-3.5" />
					</AuiIf>
					Copy
				</ActionBarPrimitive.Copy>
			</ActionBarPrimitive.Root>
		</MessagePrimitive.Root>
	);
}

function Disclosure({ label, running, children }: Readonly<{ label: string; running: boolean; children: ReactNode }>) {
	return (
		<details open={running} className="group/disclosure border-b border-[var(--border)] last:border-b-0">
			<summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--muted-strong)]">
				<WrenchIcon className={`size-3.5 ${running ? "qodex-pulse" : ""}`} />
				{running ? `Running ${label.toLowerCase()}…` : label}
				<ChevronDownIcon className="ml-auto size-3.5 transition group-open/disclosure:rotate-180" />
			</summary>
			<div className="border-t border-[var(--border)] bg-white px-4 py-3">{children}</div>
		</details>
	);
}

const ToolFallback: ToolCallMessagePartComponent = ({ toolName, args, result, status }) => {
	const running = status.type === "running";
	const failed = status.type === "incomplete";
	return (
		<div className="my-1 overflow-hidden rounded-xl border border-[var(--border)] bg-white">
			<div className="flex items-center gap-2 border-b border-[var(--border)] px-3 py-2 font-mono text-xs">
				<span
					className={`size-1.5 rounded-full ${
						running ? "qodex-pulse bg-amber-500" : failed ? "bg-[var(--danger)]" : "bg-emerald-500"
					}`}
				/>
				<span className="font-medium text-[var(--text)]">{toolName}</span>
				<span className="ml-auto text-[var(--muted)]">{running ? "running" : failed ? "failed" : "complete"}</span>
			</div>
			<pre className="m-0 max-h-64 overflow-auto bg-[var(--code)] p-3 text-xs leading-5 text-[var(--muted-strong)]">
				{formatValue(result === undefined ? args : result)}
			</pre>
		</div>
	);
};

function formatValue(value: unknown): string {
	if (typeof value === "string") return value;
	try {
		return JSON.stringify(value, null, 2) ?? String(value);
	} catch {
		return String(value);
	}
}

function ComposerArea({ showSuggestions = false }: Readonly<{ showSuggestions?: boolean }>) {
	return (
		<div>
			<ComposerQueue />
			<Composer />
			{showSuggestions ? <QuickPrompts /> : null}
		</div>
	);
}

function ComposerQueue() {
	const { clearQueue } = usePiRuntimeExtras();
	const queueSize = useAuiState((state) => state.composer.queue.length);
	if (queueSize === 0) return null;

	return (
		<div className="mb-2 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--panel-subtle)]">
			<div className="flex items-center border-b border-[var(--border)] px-3 py-2 text-xs text-[var(--muted)]">
				<span>
					{queueSize} queued message{queueSize === 1 ? "" : "s"}
				</span>
				<button
					type="button"
					onClick={() => void clearQueue()}
					className="ml-auto flex items-center gap-1 rounded-md border-0 bg-transparent px-2 py-1 text-[var(--muted)] hover:bg-white hover:text-[var(--danger)]"
				>
					<Trash2Icon className="size-3" /> Clear
				</button>
			</div>
			<ComposerPrimitive.Queue>
				{() => (
					<div className="flex items-center gap-2 px-3 py-2 text-sm">
						<span className="font-mono text-xs text-[var(--text)]">queued</span>
						<QueueItemPrimitive.Text className="truncate text-[var(--muted)]" />
					</div>
				)}
			</ComposerPrimitive.Queue>
		</div>
	);
}

function Composer() {
	const aui = useAui();
	const { status } = usePiRuntimeExtras();
	const isEmpty = useAuiState((state) => state.composer.isEmpty);
	const text = useAuiState((state) => state.composer.text);
	const showCancel = status === "running" && isEmpty;
	const picker = useRef<HTMLInputElement>(null);
	const [file, setFile] = useState<File | null>(null);
	const [skillSelected, setSkillSelected] = useState(false);
	const [uploading, setUploading] = useState(false);
	const [build, setBuild] = useState<{ kbId: string; job: BuildJob } | null>(null);
	const [buildError, setBuildError] = useState("");
	const command = text.trim().toLowerCase();
	const showSkill =
		!skillSelected &&
		command.startsWith("/") &&
		(KB_SKILL_COMMAND.startsWith(command) || "/build-knowledge-base".startsWith(command));
	const usesLibrary = !!file || skillSelected;
	const runningBuild = uploading || build?.job.status === "running";

	function selectSkill() {
		setSkillSelected(true);
		setBuildError("");
		aui.composer.setText("");
	}

	async function buildKnowledgeBase() {
		if (!file || !skillSelected || runningBuild) return;
		setUploading(true);
		setBuild(null);
		setBuildError("");
		try {
			const body = new FormData();
			body.set("file", file);
			const response = await fetch("/api/kb/books/upload", { method: "POST", body });
			const data = await response.json();
			if (!response.ok) throw new Error(data.error || "上传失败");
			setBuild(data as { kbId: string; job: BuildJob });
			setFile(null);
			aui.composer.setText("");
		} catch (error) {
			setBuildError(error instanceof Error ? error.message : "上传失败");
		} finally {
			setUploading(false);
		}
	}

	const activeBuildId = build?.job.status === "running" ? build.job.id : undefined;
	const kbId = build?.kbId;
	useEffect(() => {
		if (!activeBuildId || !kbId) return;
		const abort = new AbortController();
		const params = new URLSearchParams({ kbId, jobId: activeBuildId });
		const timer = window.setInterval(async () => {
			try {
				const response = await fetch(`/api/kb/books/upload?${params}`, {
					cache: "no-store",
					signal: abort.signal,
				});
				if (response.ok && !abort.signal.aborted) {
					setBuild({ kbId, job: (await response.json()) as BuildJob });
					setBuildError("");
				}
			} catch {
				if (!abort.signal.aborted) setBuildError("暂时无法读取构建进度，正在重试。");
			}
		}, 1500);
		return () => {
			window.clearInterval(timer);
			abort.abort();
		};
	}, [activeBuildId, kbId]);

	return (
		<ComposerPrimitive.Root className="rounded-[20px] border border-[var(--border-strong)] bg-white p-2 shadow-[0_10px_35px_rgba(20,20,15,0.07)] transition focus-within:border-[#b8b8b2] focus-within:shadow-[0_12px_40px_rgba(20,20,15,0.09)]">
			{(file || skillSelected) && (
				<div className="flex flex-wrap gap-2 px-3 py-1.5 text-sm">
					{skillSelected && (
						<span className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-2 py-1">
							<SparklesIcon className="size-3.5" />
							知识库制作 · {KB_SKILL_COMMAND}
							<button
								type="button"
								aria-label="取消引用知识库制作 skill"
								disabled={runningBuild}
								onClick={() => setSkillSelected(false)}
							>
								×
							</button>
						</span>
					)}
					{file && (
						<span className="inline-flex min-w-0 items-center gap-2 rounded-lg border border-[var(--border)] px-2 py-1">
							<span className="truncate" title={file.name}>
								{file.name}
							</span>
							<button type="button" aria-label="移除附件" disabled={runningBuild} onClick={() => setFile(null)}>
								×
							</button>
						</span>
					)}
				</div>
			)}
			<ComposerPrimitive.Input
				placeholder={skillSelected ? "附加书籍文件后，点击制作知识库" : "描述你的需求，或输入 / 选择技能…"}
				readOnly={skillSelected}
				submitMode={usesLibrary || showSkill ? "none" : "enter"}
				onKeyDown={(event) => {
					if (showSkill && event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
						event.preventDefault();
						selectSkill();
					}
				}}
				rows={1}
				className="max-h-40 min-h-[58px] w-full resize-none border-0 bg-transparent px-3 py-2 text-[15px] leading-6 text-[var(--text)] outline-none placeholder:text-[#9b9b96]"
			/>
			{showSkill && (
				<div className="mx-2 mb-2 rounded-xl border border-[var(--border)] p-1">
					<button
						type="button"
						className="w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--panel-subtle)]"
						onClick={selectSkill}
					>
						<span className="block font-medium">知识库制作</span>
						<span className="text-[var(--muted)]">{KB_SKILL_COMMAND}</span>
					</button>
				</div>
			)}
			{file && !skillSelected && <p className="px-3 pb-2 text-sm text-[var(--muted)]">输入 / 选择知识库制作技能。</p>}
			{build && (
				<output className="block px-3 pb-2 text-sm text-[var(--text)]">
					{build.job.skill} · {build.job.book} · {build.job.message}
					{build.job.status === "done" && (
						<a href="#kb" className="ml-2 underline">
							查看知识库
						</a>
					)}
				</output>
			)}
			{buildError && (
				<p role="alert" className="px-3 pb-2 text-sm text-red-700">
					{buildError}
				</p>
			)}
			<div className="flex items-center gap-1.5 px-1 pb-1">
				<input
					ref={picker}
					type="file"
					accept=".pdf,.docx,.doc,.txt,.md"
					hidden
					onChange={(event) => {
						const selected = event.target.files?.[0];
						event.target.value = "";
						if (!selected) return;
						if (
							!/\.(pdf|docx|doc|txt|md)$/i.test(selected.name) ||
							selected.size === 0 ||
							selected.size > 300 * 1024 * 1024
						) {
							setBuildError("请选择不超过 300 MB 的 PDF、DOC、DOCX、TXT 或 MD 文件。");
							return;
						}
						setFile(selected);
						setBuildError("");
					}}
				/>
				<button
					type="button"
					className="composer-icon-button"
					disabled={runningBuild}
					onClick={() => picker.current?.click()}
				>
					<PlusIcon className="size-4" />
					<span className="sr-only">添加附件</span>
				</button>
				<ModelPicker />
				<div className="ml-auto flex items-center gap-1.5">
					<ComposerPrimitive.Dictate className="composer-icon-button">
						<MicIcon className="size-4" />
						<span className="sr-only">Dictate message</span>
					</ComposerPrimitive.Dictate>
					{usesLibrary ? (
						<button
							type="button"
							className="qx-btn primary"
							disabled={!file || !skillSelected || runningBuild}
							onClick={() => void buildKnowledgeBase()}
						>
							{uploading ? "正在上传…" : "制作知识库"}
						</button>
					) : showCancel ? (
						<ComposerPrimitive.Cancel className="flex size-8 items-center justify-center rounded-xl border-0 bg-[var(--text)] text-white transition hover:bg-black">
							<SquareIcon className="size-3 fill-current" />
							<span className="sr-only">Stop generating</span>
						</ComposerPrimitive.Cancel>
					) : (
						<ComposerPrimitive.Send className="flex size-8 items-center justify-center rounded-xl border-0 bg-[var(--text)] text-white transition hover:bg-black disabled:bg-[#d2d2ce] disabled:text-white">
							<ArrowUpIcon className="size-4" />
							<span className="sr-only">Send message</span>
						</ComposerPrimitive.Send>
					)}
				</div>
			</div>
		</ComposerPrimitive.Root>
	);
}

function ModelPicker() {
	const { metadata, setModel, status } = usePiRuntimeExtras();
	const modelId = metadata.config?.modelId ?? "deepseek-flash";
	const provider = metadata.config?.provider ?? "deepseek";
	const value = `${provider}/${modelId}`;
	const [models, setModels] = useState<PiModelInfo[]>([]);
	useEffect(() => {
		const abort = new AbortController();
		fetch("/api/pi/models", { signal: abort.signal })
			.then(async (r) => {
				if (r.ok) setModels((await r.json()) as PiModelInfo[]);
			})
			.catch(() => {});
		return () => abort.abort();
	}, []);

	return (
		<label className="relative flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs font-medium text-[var(--muted-strong)] transition hover:bg-[var(--hover)]">
			<SparklesIcon className="size-3.5 text-[#5966d8]" />
			<select
				aria-label="Model"
				value={value}
				disabled={status === "running"}
				onChange={(event) => {
					const selection = parseModelSelection(event.target.value);
					if (selection) void setModel(selection);
				}}
				className="appearance-none border-0 bg-transparent pr-4 text-xs font-medium text-[var(--muted-strong)] outline-none disabled:opacity-50"
			>
				{!models.some((m) => `${m.provider}/${m.modelId}` === value) && (
					<option value={value}>
						{provider} / {modelId}
					</option>
				)}
				{models.map((m) => (
					<option key={`${m.provider}/${m.modelId}`} value={`${m.provider}/${m.modelId}`}>
						{m.name || m.modelId} · {m.provider}
					</option>
				))}
			</select>
			<ChevronDownIcon className="pointer-events-none absolute right-1.5 size-3 text-[var(--muted)]" />
		</label>
	);
}

function QuickPrompts() {
	const aui = useAui();
	return (
		<div className="mx-auto mt-3 flex max-w-[720px] flex-wrap justify-center gap-2">
			{SUGGESTIONS.map((suggestion) => (
				<button
					key={suggestion}
					type="button"
					onClick={() => aui.composer.setText(suggestion)}
					className="rounded-xl border border-[var(--border)] bg-white px-3 py-1.5 text-xs text-[var(--muted-strong)] shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition hover:border-[var(--border-strong)] hover:bg-[var(--hover)] hover:text-[var(--text)]"
				>
					{suggestion}
				</button>
			))}
		</div>
	);
}
