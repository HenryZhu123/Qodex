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
	useAui,
	useAuiState,
	type ToolCallMessagePartComponent,
} from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import { usePiRuntimeExtras, usePiThreadState } from "@assistant-ui/react-pi";
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
import type { ReactNode } from "react";

const SUGGESTIONS = [
	"Inspect this workspace",
	"Explain the architecture",
	"Find a bug",
	"Run the tests",
	"Plan a refactor",
	"Review recent changes",
];

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
						<ThreadPrimitive.ViewportFooter className="sticky bottom-0 mt-auto bg-gradient-to-t from-white via-white to-transparent pb-5 pt-10">
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
				<SparklesIcon className="size-[18px]" />
			</div>
			<h1 className="m-0 text-[32px] font-semibold tracking-[-0.045em] text-[var(--text)] sm:text-[36px]">
				How can I help you today?
			</h1>
			<p className="mx-auto mt-3 max-w-lg text-sm leading-6 text-[var(--muted)]">
				Ask Qodex to understand your codebase, run tools, or work through a change with you.
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
				<span>{queueSize} queued message{queueSize === 1 ? "" : "s"}</span>
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
	const { status } = usePiRuntimeExtras();
	const isEmpty = useAuiState((state) => state.composer.isEmpty);
	const showCancel = status === "running" && isEmpty;

	return (
		<ComposerPrimitive.Root className="rounded-[20px] border border-[var(--border-strong)] bg-white p-2 shadow-[0_10px_35px_rgba(20,20,15,0.07)] transition focus-within:border-[#b8b8b2] focus-within:shadow-[0_12px_40px_rgba(20,20,15,0.09)]">
			<ComposerPrimitive.Input
				placeholder="Send a message…"
				rows={1}
				className="max-h-40 min-h-[58px] w-full resize-none border-0 bg-transparent px-3 py-2 text-[15px] leading-6 text-[var(--text)] outline-none placeholder:text-[#9b9b96]"
			/>
			<div className="flex items-center gap-1.5 px-1 pb-1">
				<ComposerPrimitive.AddAttachment className="composer-icon-button">
					<PlusIcon className="size-4" />
					<span className="sr-only">Add attachment</span>
				</ComposerPrimitive.AddAttachment>
				<ModelPicker />
				<div className="ml-auto flex items-center gap-1.5">
					<ComposerPrimitive.Dictate className="composer-icon-button">
						<MicIcon className="size-4" />
						<span className="sr-only">Dictate message</span>
					</ComposerPrimitive.Dictate>
					{showCancel ? (
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
	const provider = metadata.config?.provider ?? "talkweb";
	const value = `${provider}/${modelId}`;

	return (
		<label className="relative flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs font-medium text-[var(--muted-strong)] transition hover:bg-[var(--hover)]">
			<SparklesIcon className="size-3.5 text-[#5966d8]" />
			<select
				aria-label="Model"
				value={value}
				disabled={status === "running"}
				onChange={(event) => {
					const [nextProvider, nextModelId] = event.target.value.split("/", 2);
					if (nextProvider && nextModelId) void setModel({ provider: nextProvider, modelId: nextModelId });
				}}
				className="appearance-none border-0 bg-transparent pr-4 text-xs font-medium text-[var(--muted-strong)] outline-none disabled:opacity-50"
			>
				<option value="talkweb/deepseek-flash">DeepSeek Flash</option>
				<option value="talkweb/gpu-qwen3.8-27b">Qwen 3.8 27B</option>
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
