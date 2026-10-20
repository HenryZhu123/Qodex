"""检查模板中有错样本的各列填法，以及JSONL正样本结构。"""
import json
from collections import Counter
from openpyxl import load_workbook

TPL = r'C:\hyt-agent\数据集\完整数据集标点符号.xlsx'
JL = r'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集_v2.jsonl'

wb = load_workbook(TPL, read_only=True)
ws = wb['Sheet1']
header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
rows = [dict(zip(header, r)) for r in ws.iter_rows(min_row=2, values_only=True)]
wb.close()

pos = [r for r in rows if r['is_real_error']]
neg = [r for r in rows if not r['is_real_error']]
print(f'模板: 总{len(rows)}行, 有错{len(pos)}, 无错{len(neg)}')
print()

# 正样本前2行完整展示
for r in pos[:2]:
    print(f'===== 有错样本 id={r["id"]} =====')
    for k in header:
        v = str(r[k])[:250] if r[k] is not None else 'None'
        print(f'  {k}: {v}')
    print()

# 无错样本是否 correction 等列全为 None
neg_nonnull = Counter(k for r in neg for k in header if r[k] is not None)
print('无错样本非空列分布:', dict(neg_nonnull))
print()

# 有错样本各列非空统计
pos_nonnull = Counter(k for r in pos for k in header if r[k] is not None)
print('有错样本非空列分布:', dict(pos_nonnull))
print()

# error_cnt 分布
print('有错 error_cnt 分布:', dict(Counter(r['error_cnt'] for r in pos)))
print('无错 error_cnt 分布:', dict(Counter(r['error_cnt'] for r in neg)))
print()

# school/file_name/title 的取值
print('school 取值(前10):', [k for k, _ in Counter(r['school'] for r in rows).most_common(10)])
print('file_name 取值(前10):', [k for k, _ in Counter(r['file_name'] for r in rows).most_common(10)])
print('title 取值(前15):', [k for k, _ in Counter(r['title'] for r in rows).most_common(15)])
print('model_name 取值:', dict(Counter(r['model_name'] for r in rows)))
print('error_detailed_type 取值:', dict(Counter(r['error_detailed_type'] for r in pos)))
print('is_content_same 分布(有错):', dict(Counter(r['is_content_same'] for r in pos)))

# ============ JSONL 侧 ============
print()
print('=' * 60)
with open(JL, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 第一条正样本
shown = 0
refs = []
for line in lines:
    d = json.loads(line)
    sys_c = user_c = asst_c = ''
    for m in d['messages']:
        if m['role'] == 'system':
            sys_c = m['content']
        elif m['role'] == 'user':
            user_c = m['content']
        else:
            asst_c = m['content']
    # 提取 payload
    payload_str = user_c.split('[INPUT_PAYLOAD]', 1)[1].strip()
    payload = json.loads(payload_str)
    refs.append(payload['reference'])
    a = json.loads(asst_c)
    if a['has_error'] and shown < 2:
        shown += 1
        print(f'===== JSONL 正样本 =====')
        print('reference:', payload['reference'])
        print('detection_content 前200:', payload['detection_content'][:200])
        print('assistant:')
        print(json.dumps(a, ensure_ascii=False, indent=1)[:1500])
        print()

# reference 的结构样例
print('reference 样例(3条):')
for s in refs[:3]:
    print(' ', s.replace('\n', ' | '))
# 试卷标题去掉# 后是否就是 file_name 去掉.pdf
import re
mapping_ok = 0
for line in lines[:50]:
    d = json.loads(line)
    user_c = [m['content'] for m in d['messages'] if m['role'] == 'user'][0]
    payload = json.loads(user_c.split('[INPUT_PAYLOAD]', 1)[1].strip())
    m1 = re.search(r'【试卷标题】(.+)', payload['reference'])
    m2 = re.search(r'【学科】(.+)', payload['reference'])
    m3 = re.search(r'【题型或其它信息】(.+)', payload['reference'])
    if m1:
        print(f"  试卷标题={m1.group(1).strip()!r} 学科={m2.group(1).strip() if m2 else ''!r} 题型={m3.group(1).strip() if m3 else ''!r}")
