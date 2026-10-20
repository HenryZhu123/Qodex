"""验证假设：模板 content + v2 错误注入 == v2 detection_content（按顺序 580 正样本）。"""
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


def norm(s):
    """统一换行表示：字面 \\n 与真实换行视为等价（仅用于比对，不改写数据）。"""
    return str(s).replace('\\n', '\n') if s is not None else s


def inject(clean, e):
    """把错误注入干净文本：在 clean 中找 correction（干净文本片段），替换为 original_text（带错误的文本片段）。"""
    co = e.get('correction', '')
    ot = e.get('original_text', '')
    at = e.get('anchor_text', '')
    if co == ot:
        return None
    # 位置优先级：anchor 上下文 > 直接找 correction > 直接找 ot
    if at:
        ai = clean.find(at)
        if ai >= 0:
            rel = at.find(co)
            if rel >= 0:
                s = ai + rel
                return clean[:s] + ot + clean[s + len(co):]
            rel2 = at.find(ot)
            if rel2 >= 0:
                s = ai + rel2
                return clean[:s] + co + clean[s + len(ot):] if False else clean[:s] + ot.replace(co, ot) + clean[s + len(ot):] if False else None
    i = clean.find(co)
    if i >= 0:
        return clean[:i] + ot + clean[i + len(co):]
    return None


ok = fail = none_case = 0
fail_cases = []
for j, t in zip(pos_jl, pos_tpl):
    clean = t['content']
    e = j['a']['errors'][0]
    r = inject(clean, e)
    if r is None:
        none_case += 1
        fail_cases.append((j, t, '定位失败'))
        continue
    if norm(r) == norm(j['dc']):
        ok += 1
    else:
        fail += 1
        fail_cases.append((j, t, '内容不同'))

print(f'580 正样本: 注入验证成功 {ok} | 失败 {fail} | 定位失败 {none_case}')
print()

# 失败案例细分
shown = 0
for j, t, why in fail_cases:
    if shown >= 6:
        break
    shown += 1
    e = j['a']['errors'][0]
    print(f'===== id={t["id"]} ({why}) =====')
    print(f'  v2 original_text: {e["original_text"]!r}')
    print(f'  v2 correction:    {e["correction"]!r}')
    print(f'  v2 anchor_text:   {str(e["anchor_text"])[:70]!r}')
    # 差异定位
    dc_n, ct_n = norm(j['dc']), norm(t['content'])
    if len(dc_n) == len(ct_n):
        diffs = [(i, ct_n[i], dc_n[i]) for i in range(len(dc_n)) if ct_n[i] != dc_n[i]]
        print(f'  等长差异({len(diffs)}处):', [(i, a, b) for i, a, b in diffs[:5]])
    else:
        # 找公共前后缀
        p = 0
        while p < min(len(dc_n), len(ct_n)) and dc_n[p] == ct_n[p]:
            p += 1
        s = 0
        while s < min(len(dc_n), len(ct_n)) - p and dc_n[-1 - s] == ct_n[-1 - s]:
            s += 1
        print(f'  长度{len(ct_n)}->{len(dc_n)}, 公共前缀{p}, 公共后缀{s}')
        print(f'  干净段: {ct_n[max(0,p-15):len(ct_n)-s+15]!r}')
        print(f'  错误段: {dc_n[max(0,p-15):len(dc_n)-s+15]!r}')
    print()

# 负样本的 content 验证：481 条中 dc == 模板content (norm后)
neg_jl = [j for j in jl if not j['a']['has_error']]
neg_tpl = [t for t in tpl_rows if not t['is_real_error']]
neg_ok = sum(1 for j, t in zip(neg_jl, neg_tpl) if norm(j['dc']) == norm(t['content']))
print(f'负样本 dc==模板content(norm后): {neg_ok}/481')
