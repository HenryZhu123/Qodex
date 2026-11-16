import assert from "node:assert/strict";
import { test } from "node:test";
import { paperRequest, preset408 } from "../lib/paper-plan.ts";

test("408 plan expands ordered four-subject 40+7 slots without rescaling", () => {
	const plan = paperRequest(preset408(), "测试卷", "offline");
	assert.equal(plan.schema_version, "2.0");
	assert.equal(plan.question_count, 47);
	assert.equal(plan.total_score, 150);
	assert.equal(new Set(plan.slots.map((s) => s.subject)).size, 4);
	assert.ok(plan.slots.slice(0, 40).every((s) => s.question_type === "single_choice"));
	assert.ok(plan.slots.slice(40).every((s) => s.question_type === "comprehensive"));
	assert.deepEqual(plan.slots[40].part_scores, [2, 6]);
});

test("invalid subpart sums, counts, blank names and excessive paper size are rejected", () => {
	for (const change of [{ count: 0 }, { count: 101 }, { score: 0 }, { partScores: "3,4" }, { subject: " " }]) {
		const groups = preset408();
		groups[4] = { ...groups[4], ...change };
		assert.throws(() => paperRequest(groups, "测试", "offline"));
	}
	assert.throws(() => paperRequest(preset408(), " ", "offline"));
});

test("empty optional constraints remain unrestricted and row order is respected", () => {
	const groups = preset408().slice(4, 5);
	groups[0].partScores = "";
	const plan = paperRequest(groups, "测试", "offline");
	assert.equal(plan.question_count, 1);
	assert.equal("part_scores" in plan.slots[0], false);
	assert.equal("knowledge_point" in plan.slots[0], false);
	assert.equal("difficulty" in plan.slots[0], false);
});
