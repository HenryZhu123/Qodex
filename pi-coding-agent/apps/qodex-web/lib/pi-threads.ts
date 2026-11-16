import type { PiClient } from "@assistant-ui/react-pi";

/** Sidebar rows are one line; anything longer is cut with an ellipsis. */
export const THREAD_TITLE_MAX = 24;

/** First user message → a readable sidebar title. */
export function threadTitleFrom(content: string): string {
	const title = content.replace(/\s+/g, " ").trim();
	return title.length > THREAD_TITLE_MAX ? `${title.slice(0, THREAD_TITLE_MAX)}…` : title;
}

type NamingClient = Pick<PiClient, "getThread" | "renameThread">;

/**
 * Name a brand-new conversation from its first message, and invalidate the
 * thread catalog on the way.
 *
 * The catalog is cached per workspace and only invalidated by membership
 * changes (create, rename, archive, delete). A list request that lands between
 * creating a thread and the first write to its session file latches a snapshot
 * without that thread, and nothing clears it afterwards: the conversation then
 * disappears from "最近对话" until the process restarts. Renaming is the
 * supported way to invalidate it, and it also replaces "Untitled thread" with
 * something readable. A named thread is left alone, and naming never blocks a
 * message: failures are swallowed deliberately.
 *
 * Returns whether a rename happened, which is what the test asserts.
 */
export async function nameUntitledThread(piClient: NamingClient, threadId: string, content: string): Promise<boolean> {
	const title = threadTitleFrom(content);
	if (!title) return false;
	try {
		const snapshot = await piClient.getThread(threadId);
		if (snapshot.metadata.title) return false;
		await piClient.renameThread(threadId, title);
		return true;
	} catch {
		return false;
	}
}
