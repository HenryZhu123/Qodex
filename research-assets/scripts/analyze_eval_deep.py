# -*- coding: utf-8 -*-
"""深入分析：FP 误报内容模式、FN 案例、跳过行特征、FP 计数差异"""
import json
from collections import Counter
from openpyxl import load_workbook

wb = load_workbook(r'C:\Users\ASUS\Downloads\train_v1.1_智能评估.xlsx', read_only=True)
ws = wb['聚合检测']
header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
rows = [dict(zip(header, r)) for r in ws.iter_rows(min_row=2, values_only=True)]
wb.close()

def parse_errors(v):
    if not v:
        return []
    try:
        el = json.loads(v) if isinstance(v, str) else v
        return el if isinstance(el, list) else []
    except Exception:
        return []

# ---------- 0. 验证 FP 计数差异 ----------
fp_raw_vals = Counter()
for r in rows:
    v = r.get('FP')
    fp_raw_vals[repr(v)] += 1
print(f'FP 原始值分布: {dict(fp_raw_vals)}')
tp_raw = Counter(repr(r.get('TP')) for r in rows)
print(f'TP 原始值分布: {dict(tp_raw)}')

# 检查 metrics FP=139 与行级 125 的差异：可能包含 skipped 行被算作 FP？
# 按 is_real_error 与 has_error 交叉
cross = Counter((r.get('is_real_error'), str(r.get('has_error'))) for r in rows)
print(f'is_real_error x has_error 交叉: {dict(cross)}')

# ---------- 1. FP 误报明细（按类型分组，提取模型报的错和 gold_reason） ----------
print('\n' + '='*90)
print('FP 误报明细')
print('='*90)
fp_rows = [r for r in rows if r.get('FP') == 1]

for gold_type in ['错别字', '选项结构错误', '题目与题型不一致']:
    sub = [r for r in fp_rows if r.get('error_type') == gold_type]
    print(f'\n--- gold 类型: {gold_type}（{len(sub)} 条 FP） ---')
    # 统计模型报的错都改了什么
    patterns = []
    for r in sub:
        errs = parse_errors(r.get('errors'))
        for e in errs:
            orig = str(e.get('original_text', ''))[:20]
            corr = str(e.get('correction', ''))[:20]
            desc = str(e.get('description', ''))[:50]
            patterns.append((orig, corr, desc))
    print(f'共报出 {len(patterns)} 处"错误"，典型内容：')
    for p in patterns[:15]:
        print(f'    "{p[0]}" → "{p[1]}" | {p[2]}')

# ---------- 2. FN 漏报深挖 ----------
print('\n' + '='*90)
print('FN 漏报深挖（gold 有错但模型/系统判定无错）')
print('='*90)
fn_rows = [r for r in rows if r.get('FN') == 1]
for r in fn_rows:
    rid = r.get('id')
    gold_errs = parse_errors(r.get('correction')) if r.get('correction') else []
    print(f"\nid={rid} [{r.get('error_type')}] gold共{r.get('error_cnt')}处错:")
    for e in gold_errs:
        print(f"    gold错: '{str(e.get('original_text',''))[:30]}' → '{str(e.get('correction',''))[:30]}' | {str(e.get('description',''))[:60]}")
    model_errs = parse_errors(r.get('errors'))
    print(f"    模型输出: has_error={r.get('has_error')}, 报{len(model_errs)}条错")
    for e in model_errs:
        print(f"      模型报: '{str(e.get('original_text',''))[:30]}' → '{str(e.get('correction',''))[:30]}'")
    print(f"    评估reason: {str(r.get('reason') or '')[:150]}")
    # 题面前120字
    ec = str(r.get('error_content') or '')
    print(f"    题面: {ec[:100].replace(chr(10), ' / ')}")

# ---------- 3. 跳过行分析（98条） ----------
print('\n' + '='*90)
print('跳过行分析（skipped_failed_detection / parse_fail）')
print('='*90)
unmarked = [r for r in rows if r.get('TP') is None and r.get('TN') is None and r.get('FN') is None and r.get('FP') is None]
# 这些行的 is_real_error 分布
sk_pos = sum(1 for r in unmarked if r.get('is_real_error') == 1)
sk_neg = sum(1 for r in unmarked if r.get('is_real_error') == 0)
print(f'跳过行中 正样本(is_real_error=1): {sk_pos}, 负样本: {sk_neg}')

# 错别字检测模式分布
mode = Counter(str(r.get('错别字检测模式')) for r in unmarked)
print(f'跳过行 错别字检测模式: {dict(mode)}')
mode_all = Counter(str(r.get('错别字检测模式')) for r in rows)
print(f'全体行 错别字检测模式: {dict(mode_all)}')

# failure_reason 样例
fr = Counter(str(r.get('failure_reason') or '')[:80] for r in unmarked)
for k, v in fr.most_common(5):
    print(f'failure_reason: {k} x {v}')

# 对比：成功行里 post_routing_filter 也出现吗
pf_success = [r for r in rows if str(r.get('failure_type')) == 'post_routing_filter' and r.get('TP') is not None]
print(f'failure_type=post_routing_filter 但有标记的行: {len(pf_success)}')

# ---------- 4. 跳过行的 is_real_error=1 的（正样本被跳过=实际漏报） ----------
sk_pos_rows = [r for r in unmarked if r.get('is_real_error') == 1]
print(f'\n跳过的正样本（等于实际漏报）: {len(sk_pos_rows)} 条')
for r in sk_pos_rows[:15]:
    gold_errs = parse_errors(r.get('correction')) if r.get('correction') else []
    ge = ''
    if gold_errs:
        ge = f"'{str(gold_errs[0].get('original_text',''))[:25]}'→'{str(gold_errs[0].get('correction',''))[:25]}'"
    print(f"  id={r.get('id')} [{r.get('error_type')}] {ge}")
