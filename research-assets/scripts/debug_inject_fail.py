"""调试正向注入失败的行：repair 成功但 inject 还原失败的原因。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from punct_repair import minimal_diff

from openpyxl import load_workbook

JL = r'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集_v2.jsonl'
OUT = r'C:\hyt-agent\数据集\完整数据集标点符号_v2.xlsx'

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

wb = load_workbook(OUT)
ws = wb['Sheet1']
header = [c.value for c in ws[1]]
rows = [dict(zip(header, r)) for r in ws.iter_rows(min_row=2, values_only=True)]
wb.close()


def inject(clean, err):
    ot = str(err.get('original_text', ''))
    co = str(err.get('correction', ''))
    at = str(err.get('anchor_text', ''))
    if ot == co:
        return clean
    p, om, cm = minimal_diff(ot, co)
    if om == '' and cm == '':
        return clean
    # anchor 优先
    if at:
        ai = clean.find(at)
        if ai >= 0:
            rel = at.find(co)
            if rel >= 0:
                st = ai + rel
                if clean[st:st + len(co)] == co:
                    abs_start = st + p
                    if clean[abs_start:abs_start + len(cm)] == cm:
                        return clean[:abs_start] + om + clean[abs_start + len(cm):]
    st = clean.find(co)
    if st >= 0 and clean[st:st + len(co)] == co:
        abs_start = st + p
        if clean[abs_start:abs_start + len(cm)] == cm:
            return clean[:abs_start] + om + clean[abs_start + len(cm):]
    return None


fails = []
for r, j in zip(rows, jl):
    if not r['is_real_error']:
        continue
    out = r['content']
    for e in j['a']['errors']:
        out = inject(out, e)
        if out is None:
            fails.append((r['id'], '定位失败', None))
            break
    else:
        if out != r['error_content']:
            fails.append((r['id'], '结果不等', out))
            continue

print(f'注入失败总数: {len(fails)}')
loc_fail = [f for f in fails if f[1] == '定位失败']
res_fail = [f for f in fails if f[1] == '结果不等']
print(f'  定位失败: {len(loc_fail)} | 结果不等: {len(res_fail)}')
print()

# 逐个分析"结果不等"的差异
for rid, why, out in res_fail[:6]:
    r = rows[rid - 1]
    j = jl[rid - 1]
    e = j['a']['errors'][0]
    dc, ct = r['error_content'], r['content']
    if out is not None:
        # 找 out 与 dc 的差异
        if len(out) == len(dc):
            diffs = [(i, out[i], dc[i]) for i in range(len(out)) if out[i] != dc[i]]
            print(f'===== id={rid} 等长差异({len(diffs)}处) =====')
            print(f'  前3处: {diffs[:3]}')
        else:
            p = 0
            while p < min(len(out), len(dc)) and out[p] == dc[p]:
                p += 1
            s = 0
            while s < min(len(out), len(dc)) - p and out[-1 - s] == dc[-1 - s]:
                s += 1
            print(f'===== id={rid} 长度{len(out)}->{len(dc)} =====')
            print(f'  ot: {e["original_text"]!r} -> co: {e["correction"]!r}')
            print(f'  inject产出: {out[max(0,p-10):len(out)-s+10]!r}')
            print(f'  error_content: {dc[max(0,p-10):len(dc)-s+10]!r}')
    # cm 出现次数
    co = str(e.get('correction',''))
    cnt_in_ct = ct.count(co)
    print(f'  correction片段在content中出现次数: {cnt_in_ct}')
    print()
