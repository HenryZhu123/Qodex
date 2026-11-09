"use client";

import { Maximize2Icon, MoreHorizontalIcon, PanelsTopLeftIcon } from "lucide-react";
import { useState } from "react";
import { QodexThread } from "@/components/qodex-thread";
import { QodexThreadList } from "@/components/qodex-thread-list";
import { RuntimeStatus } from "@/components/runtime-status";
import { QodexRuntimeProvider } from "./runtime-provider";

export default function Home() {
	const [sidebarOpen, setSidebarOpen] = useState(true);

	return (
		<QodexRuntimeProvider>
			<div className="h-dvh overflow-hidden bg-[var(--canvas)] p-2 sm:p-4 lg:p-5">
				<div className="mx-auto flex h-full min-h-0 max-w-[1500px] overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--panel-raised)] shadow-[0_20px_60px_rgba(25,25,20,0.06)]">
					<aside
						className={`${sidebarOpen ? "md:flex" : "md:hidden"} hidden w-[272px] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--sidebar)]`}
					>
						<div className="flex h-14 shrink-0 items-center justify-between border-b border-[var(--border)] px-4">
							<div className="flex items-center gap-2.5">
								<div className="flex size-7 items-center justify-center rounded-lg border border-[var(--border-strong)] bg-[var(--text)] text-white shadow-sm">
									<PanelsTopLeftIcon className="size-3.5" strokeWidth={2.25} />
								</div>
								<span className="text-sm font-semibold tracking-[-0.015em]">Qodex</span>
							</div>
							<button
								type="button"
								aria-label="Hide sidebar"
								onClick={() => setSidebarOpen(false)}
								className="icon-button"
							>
								<PanelsTopLeftIcon className="size-4" />
							</button>
						</div>
						<QodexThreadList />
					</aside>

					<section className="flex min-w-0 flex-1 flex-col">
						<header className="flex h-14 shrink-0 items-center gap-3 border-b border-[var(--border)] px-4 sm:px-5">
							{!sidebarOpen ? (
								<button
									type="button"
									aria-label="Show sidebar"
									onClick={() => setSidebarOpen(true)}
									className="icon-button hidden md:flex"
								>
									<PanelsTopLeftIcon className="size-4" />
								</button>
							) : null}
							<div className="flex size-7 items-center justify-center rounded-lg bg-[var(--text)] text-white md:hidden">
								<PanelsTopLeftIcon className="size-3.5" />
							</div>
							<div className="min-w-0">
								<div className="truncate text-sm font-medium tracking-[-0.01em]">New chat</div>
								<div className="hidden text-[11px] text-[var(--muted)] sm:block">Local coding agent</div>
							</div>
							<div className="ml-auto flex items-center gap-1.5">
								<RuntimeStatus />
								<details className="group relative">
									<summary aria-label="More options" className="icon-button list-none">
										<MoreHorizontalIcon className="size-4" />
									</summary>
									<div className="absolute right-0 top-10 z-20 w-56 rounded-xl border border-[var(--border)] bg-white p-3 text-xs shadow-xl shadow-black/10">
										<div className="font-medium text-[var(--text)]">Local Pi runtime</div>
										<div className="mt-1 text-[var(--muted)]">talkweb / deepseek-flash</div>
									</div>
								</details>
								<button
									type="button"
									aria-label="Expand workspace"
									onClick={() => {
										if (document.fullscreenElement) void document.exitFullscreen();
										else void document.documentElement.requestFullscreen();
									}}
									className="icon-button hidden sm:flex"
								>
									<Maximize2Icon className="size-3.5" />
								</button>
							</div>
						</header>
						<main className="min-h-0 flex-1 bg-[var(--panel-raised)]">
							<QodexThread />
						</main>
					</section>
				</div>
			</div>
		</QodexRuntimeProvider>
	);
}
