"use client";

import { ThreadListItemPrimitive, ThreadListPrimitive } from "@assistant-ui/react";
import { FolderGit2Icon, LogOutIcon, MessageSquareIcon, PlusIcon, Trash2Icon } from "lucide-react";

export function QodexThreadList() {
	return (
		<ThreadListPrimitive.Root className="flex min-h-0 flex-1 flex-col px-3 py-3">
			<ThreadListPrimitive.New
				onClick={() => {
					location.hash = "chat";
				}}
				className="flex h-10 shrink-0 items-center gap-2 rounded-xl border border-[var(--border-strong)] bg-white px-3 text-left text-sm font-medium text-[var(--text)] shadow-[0_1px_2px_rgba(0,0,0,0.03)] transition hover:bg-[var(--hover)] disabled:opacity-40"
			>
				<PlusIcon className="size-4" />
				新建对话
			</ThreadListPrimitive.New>

			<div className="mt-5 px-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">
				最近对话
			</div>
			<div className="mt-2 min-h-0 flex-1 overflow-y-auto">
				<ThreadListPrimitive.Items>{() => <QodexThreadListItem />}</ThreadListPrimitive.Items>
			</div>

			<div className="-mx-3 -mb-3 mt-3 border-t border-[var(--border)] p-3">
				<div className="flex items-center gap-2.5 rounded-xl px-2 py-2 text-sm text-[var(--muted)]">
					<div className="flex size-8 items-center justify-center rounded-lg border border-[var(--border)] bg-white text-[var(--text)]">
						<FolderGit2Icon className="size-4" />
					</div>
					<div className="min-w-0 flex-1">
						<div className="truncate text-xs font-medium text-[var(--text)]">Pi Agent 会话</div>
						<div className="truncate text-[10px]">apps/qodex-web</div>
					</div>
					<LogOutIcon className="size-3.5 opacity-50" />
				</div>
			</div>
		</ThreadListPrimitive.Root>
	);
}

function QodexThreadListItem() {
	return (
		<ThreadListItemPrimitive.Root className="group mb-1 flex items-center rounded-xl text-sm text-[var(--muted-strong)] transition hover:bg-[var(--hover)] data-active:bg-white data-active:text-[var(--text)] data-active:shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
			<ThreadListItemPrimitive.Trigger
				onClick={() => {
					location.hash = "chat";
				}}
				className="flex min-w-0 flex-1 items-center gap-2.5 bg-transparent px-2.5 py-2.5 text-left text-inherit"
			>
				<MessageSquareIcon className="size-3.5 shrink-0 opacity-65" />
				<span className="truncate text-[13px]">
					<ThreadListItemPrimitive.Title fallback="Untitled thread" />
				</span>
			</ThreadListItemPrimitive.Trigger>
			<ThreadListItemPrimitive.Delete className="mr-1 rounded-lg border-0 bg-transparent p-1.5 text-[var(--muted)] opacity-0 transition hover:bg-red-50 hover:text-[var(--danger)] focus:opacity-100 group-hover:opacity-100">
				<Trash2Icon className="size-3.5" />
				<span className="sr-only">Delete thread</span>
			</ThreadListItemPrimitive.Delete>
		</ThreadListItemPrimitive.Root>
	);
}
