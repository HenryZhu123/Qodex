"""验证正样本 content 重建算法：用 errors 修复 detection_content，与模板 content 对照。"""
import json
from openpyxl import load_workbook

JL = r'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集_v2.jsonl'
TPL = r'C:\hyt-agent\数据集\完整数据集标点符号.xlsx'

jl = []
with open(JL, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        user_c = asst_c = ''
        for m in d['messages']:
            if m['role'] == 'user':
                user_c = m['content']
            elif m['role'] == 'assistant':
                asst_c = m['content']
        payload = json.loads(user_c.split('[INPUT_PAYLOAD]', 1)[1].strip())
        jl.append({'dc': payload['detection_content'], 'a': json.loads(asst_c)})

wb = load_workbook(TPL)
ws = wb['Sheet1']
header = [c.value for c in ws[1]]
tpl_rows = [dict(zip(header, r)) for r in ws.iter_rows(min_row=2, values_only=True)]
wb.close()

pos_jl = [j for j in jl if j['a']['has_error']]
pos_tpl = [t for t in tpl_rows if t['is_real_error']]


def apply_fix(text, errs, use_anchor=False):
    out = text
    for e in errs:
        ot = e.get('original_text', '')
        co = e.get('correction', '')
        if ot == co:
            continue
        # 优先用 anchor_text 定位，在 anchor 范围内找 original_text
        if use_anchor:
            at = e.get('anchor_text', '')
            if at and at in out and ot in at:
                # 在 anchor 内找 original_text 的位置，映射回全文
                a_start = out.find(at)
                rel = at.find(ot)
                if rel >= 0:
                    abs_start = a_start + rel
                    out = out[:abs_start] + co + out[abs_start + len(ot):]
                    continue
        idx = out.find(ot)
        if idx >= 0:
            out = out[:idx] + co + out[idx + len(ot):]
    return out


# 基础版 vs anchor 版
basic_ok = anchor_ok = 0
fails = []
for j, t in zip(pos_jl, pos_tpl):
    if j['dc'] != t['error_content']:
        continue  # 只验证 dc 相同的（错误相同，模板 content 是权威干净原文）
    r1 = apply_fix(j['dc'], j['a']['errors'])
    r2 = apply_fix(j['dc'], j['a']['errors'], use_anchor=True)
    if r1 == t['content']:
        basic_ok += 1
    if r2 == t['content']:
        anchor_ok += 1
    if r2 != t['content']:
        fails.append((j, t, r2))

print(f'dc相同的正样本(错误未变): {112} 行')
print(f'基础find替换成功: {basic_ok} | anchor定位成功: {anchor_ok}')
print()

# 失败案例分析
for j, t, r in fails[:5]:
    e = j['a']['errors'][0]
    print(f'===== id={t["id"]} =====')
    print(f'  original_text: {e["original_text"]!r}')
    print(f'  correction:    {e["correction"]!r}')
    print(f'  anchor_text:   {str(e["anchor_text"])[:80]!r}')
    print(f'  修复结果: {r[:80]!r}')
    print(f'  模板content: {str(t["content"])[:80]!r}')
    print(f'  dc: {j["dc"][:80]!r}')
    print()
