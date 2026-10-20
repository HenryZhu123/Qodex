# -*- coding: utf-8 -*-
"""重新打开生成的 xlsx 进行全量强制校验"""
import json
import sys
from openpyxl import load_workbook

OUTPUT_PATH = r'C:\hyt-agent\测试集\test_v1.1_测试集.xlsx'
JSONL_PATH = r'C:\hyt-agent\测试集\test_v1.1.jsonl'
REQUIRED_COLUMNS = ['id', 'title', 'error_content', 'error_type', 'correction',
                    'error_cnt', 'is_real_error', 'gold_reason']
ALLOWED_TYPES = {'错别字', '选项错误', '题目与题型不一致'}

errors = []
warnings = []


def check(cond, msg):
    if cond:
        print(f'  [OK] {msg}')
    else:
        errors.append(msg)
        print(f'  [FAIL] {msg}')


wb = load_workbook(OUTPUT_PATH, data_only=True)
ws = wb['测试集']

# 1. 工作表名称与单表
check(wb.sheetnames == ['测试集'], f'工作表名称为"测试集"且唯一 (实际: {wb.sheetnames})')

# 2. 表头
header = [ws.cell(row=1, column=c).value for c in range(1, 9)]
check(header == REQUIRED_COLUMNS, f'列名及顺序完全正确 (实际: {header})')

# 3. 总行数（不含标题）
data_rows = ws.max_row - 1
check(data_rows == 234, f'总行数=234 (实际: {data_rows})')

# 4. 无多余列
max_col = ws.max_column
check(max_col == 8, f'列数=8，无多余列 (实际: {max_col})')

# 5. 收集数据
records = []
for r in range(2, ws.max_row + 1):
    rec = {col: ws.cell(row=r, column=c).value for c, col in enumerate(REQUIRED_COLUMNS, 1)}
    rec['_row'] = r
    records.append(rec)

# 6. id 检查
ids = [rec['id'] for rec in records]
check(all(isinstance(i, int) and not isinstance(i, bool) for i in ids),
      'id 全部为整数类型')
check(ids == list(range(1, 235)), f'id 为 1~234 连续且不重复 (min={min(ids)}, max={max(ids)}, unique={len(set(ids))})')

# 7. 空值检查
for col in ['title', 'error_content']:
    empties = [rec['_row'] for rec in records if rec[col] is None or str(rec[col]).strip() == '']
    check(len(empties) == 0, f'{col} 无空值 (空值行: {empties})')

# 8. error_type 检查
et_counts = {}
for rec in records:
    et_counts[rec['error_type']] = et_counts.get(rec['error_type'], 0) + 1
check(set(et_counts.keys()) <= ALLOWED_TYPES, f'error_type 仅限三个规定值 (实际: {sorted(set(et_counts.keys()))})')
print(f'  [INFO] error_type 分布: {et_counts}')

# 9. correction JSON 解析
json_parse_fail = []
for rec in records:
    c = rec['correction']
    if c is not None and str(c).strip() != '':
        try:
            parsed = json.loads(str(c))
            if not isinstance(parsed, list):
                json_parse_fail.append((rec['_row'], '不是数组'))
        except Exception as e:
            json_parse_fail.append((rec['_row'], str(e)))
check(len(json_parse_fail) == 0, f'correction 所有非空内容均可解析为合法 JSON 数组 (失败: {json_parse_fail})')

# 10. error_cnt / is_real_error
cnt_bad = []
for rec in records:
    ec = rec['error_cnt']
    if not isinstance(ec, int) or isinstance(ec, bool) or ec < 0:
        cnt_bad.append((rec['_row'], ec, type(ec).__name__))
check(len(cnt_bad) == 0, f'error_cnt 均为非负整数 (异常: {cnt_bad})')

ire_bad = []
for rec in records:
    v = rec['is_real_error']
    if v not in (0, 1) or isinstance(v, bool):
        ire_bad.append((rec['_row'], v, type(v).__name__))
check(len(ire_bad) == 0, f'is_real_error 均为 0 或 1 (异常: {ire_bad})')

# 11. error_cnt 与 is_real_error 一致性
consist_bad = []
for rec in records:
    if rec['error_cnt'] == 0 and rec['is_real_error'] != 0:
        consist_bad.append((rec['_row'], 'error_cnt=0 但 is_real_error!=0'))
    if rec['error_cnt'] > 0 and rec['is_real_error'] != 1:
        consist_bad.append((rec['_row'], 'error_cnt>0 但 is_real_error!=1'))
check(len(consist_bad) == 0, f'error_cnt 与 is_real_error 逻辑一致 (异常: {consist_bad})')

# 12. 正负样本分布
pos = sum(1 for rec in records if rec['error_cnt'] > 0)
neg = sum(1 for rec in records if rec['error_cnt'] == 0)
check(pos == 118 and neg == 116, f'正样本118/负样本116 (实际: 正{pos} 负{neg})')

exp_dist = {'错别字': (38, 39), '选项错误': (39, 39), '题目与题型不一致': (41, 38)}
dist_ok = True
for et, (p, n) in exp_dist.items():
    p_act = sum(1 for rec in records if rec['error_type'] == et and rec['error_cnt'] > 0)
    n_act = sum(1 for rec in records if rec['error_type'] == et and rec['error_cnt'] == 0)
    print(f'  [INFO] {et}: 正{p_act} 负{n_act} (期望 正{p} 负{n})')
    if p_act != p or n_act != n:
        dist_ok = False
check(dist_ok, '三种错误类型正负样本分布符合预期')

# 13. 与原始 JSONL 逐行一致（重新解析 JSONL 比对）
print('\n--- 与原始 JSONL 逐行比对 ---')
src_lines = []
with open(JSONL_PATH, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line:
            src_lines.append(json.loads(line))

check(len(src_lines) == len(records), f'原始 JSONL {len(src_lines)} 行 与 Excel {len(records)} 行 一一对应')

line_mismatch = []
for i, (src, rec) in enumerate(zip(src_lines, records)):
    msgs = {m['role']: m['content'] for m in src['messages']}
    # 比对 user payload
    uc = msgs['user']
    s, e = uc.find('{'), uc.rfind('}')
    payload = json.loads(uc[s:e + 1])
    # 比对 assistant
    asst = json.loads(msgs['assistant'])

    issues = []
    if payload.get('reference') != rec['title']:
        issues.append('title 不一致')
    if payload.get('detection_content') != rec['error_content']:
        issues.append('error_content 不一致')
    if asst.get('reason') != rec['gold_reason']:
        issues.append('gold_reason 不一致')
    if asst.get('has_error', False) != (rec['is_real_error'] == 1):
        issues.append('is_real_error 不一致')
    exp_cnt = asst.get('total_errors', 0) if asst.get('has_error', False) else 0
    if exp_cnt != rec['error_cnt']:
        issues.append('error_cnt 不一致')
    if asst.get('has_error', False):
        exp_corr = json.dumps(asst.get('errors', []), ensure_ascii=False, separators=(',', ':'))
        if exp_corr != rec['correction']:
            issues.append('correction 不一致')
    else:
        if rec['correction'] not in (None, ''):
            issues.append('负样本 correction 应为空')
    if issues:
        line_mismatch.append((i + 1, issues))

check(len(line_mismatch) == 0, f'Excel 与原始 JSONL 逐行完全一致 (异常行: {line_mismatch[:10]})')

# 14. 冻结首行 & 自动筛选
check(ws.freeze_panes == 'A2', f'冻结首行 (freeze_panes={ws.freeze_panes})')
check(ws.auto_filter.ref is not None and ws.auto_filter.ref != '',
      f'开启自动筛选 (ref={ws.auto_filter.ref})')

# 15. 自动换行
wrap_ok = True
for rec in records[:5]:  # 抽查
    for col in ['title', 'error_content', 'correction', 'gold_reason']:
        c = ws.cell(row=rec['_row'], column=REQUIRED_COLUMNS.index(col) + 1)
        if not (c.alignment.wrap_text or (rec[col] in (None, ''))):
            wrap_ok = False
check(wrap_ok, 'title/error_content/correction/gold_reason 设置自动换行')

# 16. 防公式注入（检查危险前缀单元格是否按文本存储）
inject_bad = []
for rec in records:
    for col in ['title', 'error_content', 'correction', 'gold_reason', 'error_type']:
        v = rec[col]
        if v is not None and isinstance(v, str) and v.startswith(('=', '+', '-', '@')):
            cell = ws.cell(row=rec['_row'], column=REQUIRED_COLUMNS.index(col) + 1)
            if cell.data_type != 's':
                inject_bad.append((rec['_row'], col, v[:30], cell.data_type))
check(len(inject_bad) == 0, f'危险前缀文本按字符串存储，无公式注入 (异常: {inject_bad})')

# 17. Excel 不含 system 提示词 / assistant 原始整段
leak = []
for rec in records:
    for col in ['title', 'error_content', 'error_type', 'correction', 'gold_reason']:
        v = str(rec[col])
        if '# 任务：' in v or '共享核心' in v:
            leak.append((rec['_row'], col, 'system 泄漏'))
        if '[INPUT_PAYLOAD]' in v:
            leak.append((rec['_row'], col, 'user 整段泄漏'))
check(len(leak) == 0, f'Excel 不含 system 提示词或 assistant 原始整段消息 (异常: {leak})')

# 汇总
print('\n' + '=' * 60)
if errors:
    print(f'校验失败：{len(errors)} 项')
    for e in errors:
        print(f'  - {e}')
    sys.exit(1)
else:
    print('全部校验通过 ✓')
