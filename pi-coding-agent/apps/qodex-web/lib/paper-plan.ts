export interface PaperGroup {
	id: string;
	subject: string;
	question_type: "single_choice" | "comprehensive";
	count: number;
	score: number;
	partScores: string;
	knowledgePoint: string;
	difficulty: string;
}

export function preset408(): PaperGroup[] {
	const subjects = ["数据结构", "计算机组成原理", "操作系统", "计算机网络"];
	const choices = subjects.map((subject, i) => ({
		id: `choice-${i}`,
		subject,
		question_type: "single_choice" as const,
		count: [11, 11, 10, 8][i],
		score: 2,
		partScores: "",
		knowledgePoint: "",
		difficulty: "",
	}));
	const major = [8, 10, 10, 10, 10, 10, 12].map((score, i) => ({
		id: `major-${i}`,
		subject: subjects[Math.min(3, Math.floor(i / 2))],
		question_type: "comprehensive" as const,
		count: 1,
		score,
		partScores: `${Math.floor(score / 3)},${score - Math.floor(score / 3)}`,
		knowledgePoint: "",
		difficulty: "",
	}));
	return [...choices, ...major];
}

export function paperRequest(groups: PaperGroup[], name: string, id: string) {
	if (!name.trim() || !groups.length) throw new Error("请填写试卷名称并添加题目组。");
	const slots = groups.flatMap((g) => {
		if (
			!g.subject.trim() ||
			!Number.isInteger(g.count) ||
			g.count < 1 ||
			g.count > 100 ||
			!Number.isInteger(g.score) ||
			g.score < 1 ||
			g.score > 150
		)
			throw new Error("学科不能为空，题数和分值须为有效正整数。");
		const partScores = g.partScores.trim() ? g.partScores.split(/[,，]/).map(Number) : [];
		if (
			partScores.length &&
			(g.question_type !== "comprehensive" ||
				partScores.some((n) => !Number.isInteger(n) || n <= 0) ||
				partScores.reduce((a, b) => a + b, 0) !== g.score)
		)
			throw new Error("小问分值用逗号分隔，合计须等于该大题分值。");
		return Array.from({ length: g.count }, () => ({
			subject: g.subject.trim(),
			question_type: g.question_type,
			score: g.score,
			...(partScores.length ? { part_scores: partScores } : {}),
			...(g.knowledgePoint.trim() ? { knowledge_point: g.knowledgePoint.trim() } : {}),
			...(g.difficulty ? { difficulty: g.difficulty } : {}),
		}));
	});
	if (slots.length > 100) throw new Error("一次最多100道大题（小问不单独计数）。");
	return {
		schema_version: "2.0",
		request_id: `${name.trim()} · ${id}`,
		subject: "多学科试卷",
		question_count: slots.length,
		total_score: slots.reduce((n, s) => n + s.score, 0),
		slots,
		export_pdf: false,
	};
}
