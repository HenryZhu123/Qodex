import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
	title: "Qodex Web",
	description: "assistant-ui compatibility harness for Qodex",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
	return (
		<html lang="zh-CN">
			<body>{children}</body>
		</html>
	);
}
