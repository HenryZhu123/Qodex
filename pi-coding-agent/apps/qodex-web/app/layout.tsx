import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import "./workspace.css";

export const metadata: Metadata = {
	title: "Qodex · 教师工作台",
	description: "自主命题、审校、正式题库与智能组卷工作台",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
	return (
		<html lang="zh-CN">
			<body>{children}</body>
		</html>
	);
}
