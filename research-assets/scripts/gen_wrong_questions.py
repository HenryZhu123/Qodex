# -*- coding: utf-8 -*-
"""
train_v1.1 审校错题汇总生成器
从智能评估结果中提取全部审校出错的题目，输出到 模型表现 文件夹。
错题 = FP误报 + FN漏报 + 路由跳过正样本 + 评估解析失败
"""
import json
import os
from collections import Counter
from datetime import datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

SRC = r'C:\Users\ASUS\Downloads\train_v1.1_智能评估.xlsx'
OUT_DIR = r'C:\hyt-agent\模型表现'
OUT = os.path.join(OUT_DIR, 'train_v1.1_错题汇总_checkpoint-175.xlsx')

os.makedirs(OUT_DIR, exist_ok=True)

# ---------------- 读取评估结果 ----------------
wb = load_workbook(SRC, read_only=True)
ws = wb['聚合检测']
header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
rows = [dict(zip(header, r)) for r in ws.iter_rows(min_row=2, values_only=True)]
rows = [r for r in rows if r.get('id')]

metrics = []
if 'metrics' in wb.sheetnames:
    for row in wb['metrics'].iter_rows(min_row=1, max_col=2, values_only=True):
        if row and row[0] is not None and str(row[0]).strip():
            metrics.append((str(row[0]), row[1] if len(row) > 1 else None))
wb.close()

# ---------------- 工具函数 ----------------
def parse_errors(v):
    if not v:
        return []
    try:
        el = json.loads(v) if isinstance(v, str) else v
        return el if isinstance(el, list) else []
    except Exception:
        return []

def errs_json(v):
    errs = parse_errors(v)
    return json.dumps(errs, ensure_ascii=False) if errs else ''

def errs_brief(v, maxlen=160):
    errs = parse_errors(v)
    if not errs:
        return ''
    parts = []
    for e in errs[:4]:
        ot = str(e.get('original_text', ''))[:20]
        co = str(e.get('correction', ''))[:20]
        parts.append('"' + ot + '"→"' + co + '"')
    s = '；'.join(parts)
    if len(errs) > 4:
        s += ' 等%d处' % len(errs)
    return s[:maxlen]

def classify_fp_one(e):
    ot = str(e.get('original_text', ''))
    co = str(e.get('correction', ''))
    desc = str(e.get('description', ''))
    if ot and ot == co:
        return '幻觉错别字（原文=修改）'
    if ('非选择题' in desc or '无法提取选项' in desc or '不包含选项' in desc
            or '无法进行选项结构' in desc or '不包含需要检查的选项' in desc
            or '与要求的选项结构不匹配' in desc or '与检测任务要求' in desc
            or '与需要检测的选择题' in desc or '未提供可供检查的选项' in desc):
        return '非选择题硬套选项结构检测'
    if '题目类型识别错误' in desc or '作答形式' in co or '改写' in co or '题目类型' in co:
        return '题型误判/要求改写题面'
    if '错别字或拼写错误' in desc:
        return '错别字误报（知识性改写或正确词被判错）'
    if '选项标号序列' in desc or '未按A' in desc or '标号' in desc:
        return '选项标号序列误报'
    if '重复选项' in desc or '完全相同' in desc:
        return '重复选项误报'
    if '缺失' in desc or '不完整' in desc:
        return '内容缺失类误报'
    return '其他'

def classify_fp(errs):
    return list(dict.fromkeys(classify_fp_one(e) for e in errs))

HDR_FONT = Font(bold=True, size=11)
HDR_FILL = PatternFill(start_color='DDEBF7', end_color='DDEBF7', fill_type='solid')
GUARDED = [0]

def set_cell(ws, r, c, v, wrap=True):
    cell = ws.cell(row=r, column=c)
    if isinstance(v, str) and v[:1] in ('=', '+', '-', '@'):
        cell.value = v
        cell.data_type = 's'
        GUARDED[0] += 1
    else:
        cell.value = v
    if wrap:
        cell.alignment = Alignment(wrap_text=True, vertical='top')
    return cell

def write_header(ws, cols):
    for c, name in enumerate(cols, 1):
        cell = ws.cell(row=1, column=c, value=name)
        cell.font = HDR_FONT
        cell.fill = HDR_FILL
        cell.alignment = Alignment(wrap_text=True, vertical='center')

def set_widths(ws, widths):
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = w

# ---------------- 分类 ----------------
CAT_FP = 'FP误报'
CAT_FPTP = 'FP误报+TP部分正确'
CAT_FN = 'FN漏报'
CAT_FNTP = 'FN漏报+TP部分正确'
CAT_SKR_P = '路由跳过（正样本·实际漏报）'
CAT_SKR_N = '路由跳过（负样本·未审校）'
CAT_PF_P = '评估解析失败（正样本·无法判定）'
CAT_PF_N = '评估解析失败（负样本·无法判定）'

for r in rows:
    tp, tn, fp, fn = r.get('TP'), r.get('TN'), r.get('FP'), r.get('FN')
    pos = (r.get('is_real_error') == 1)
    if fp:
        r['_cat'] = CAT_FPTP if tp else CAT_FP
    elif fn:
        r['_cat'] = CAT_FNTP if tp else CAT_FN
    elif tp or tn:
        r['_cat'] = '正确'
    else:
        if str(r.get('reason') or '').startswith('判断题'):
            r['_cat'] = CAT_SKR_P if pos else CAT_SKR_N
        else:
            r['_cat'] = CAT_PF_P if pos else CAT_PF_N

fp_rows = [r for r in rows if r.get('FP')]
fn_rows = [r for r in rows if r.get('FN')]
skp_rows = [r for r in rows if r['_cat'] == CAT_SKR_P]
skn_rows = [r for r in rows if r['_cat'] == CAT_SKR_N]
pf_rows = [r for r in rows if r['_cat'] in (CAT_PF_P, CAT_PF_N)]

CAT_ORDER = [CAT_FP, CAT_FPTP, CAT_FN, CAT_FNTP, CAT_SKR_P, CAT_PF_P]
wrong = [r for r in rows if r['_cat'] in CAT_ORDER]
wrong.sort(key=lambda r: (CAT_ORDER.index(r['_cat']), str(r.get('id'))))

fp_inst = sum(int(r.get('FP') or 0) for r in fp_rows)
fp_tp_cnt = sum(1 for r in fp_rows if r.get('TP'))
fn_tp_cnt = sum(1 for r in fn_rows if r.get('TP'))
fp_fn_overlap = sum(1 for r in rows if r.get('FP') and r.get('FN'))

pat_counter = Counter()
for r in fp_rows:
    for e in parse_errors(r.get('errors')):
        pat_counter[classify_fp_one(e)] += 1
halluc = pat_counter.get('幻觉错别字（原文=修改）', 0)

model_info = '；'.join('%s×%d' % (k, v) for k, v in
                      Counter(str(r.get('审校模型')) for r in rows).most_common() if k != 'None')
eval_info = '；'.join('%s×%d' % (k, v) for k, v in
                     Counter(str(r.get('evaluation_model')) for r in rows).most_common() if k != 'None')

def pattern_note(r):
    cat = r['_cat']
    if cat in (CAT_FP, CAT_FPTP):
        cats = classify_fp(parse_errors(r.get('errors')))
        return '；'.join(cats) if cats else '（模型errors为空）'
    if cat in (CAT_FN, CAT_FNTP):
        m = len(parse_errors(r.get('errors')))
        g = r.get('error_cnt') or 0
        return '模型完全未报错（gold共%d处）' % g if m == 0 else '模型检出%d处但遗漏gold错误（gold共%d处）' % (m, g)
    if cat == CAT_SKR_P:
        return '判断题被路由过滤（post_routing_filter），整题未送检'
    return '评估模型解析失败（evaluation_status=parse_fail），无法判定'

# ---------------- Sheet 1: 总览 ----------------
out_wb = Workbook()
ws1 = out_wb.active
ws1.title = '总览'
title_font = Font(bold=True, size=14)

ov = []
ov.append(('train_v1.1 审校错题汇总（模型表现）', ''))
ov.append(('', ''))
ov.append(('生成时间', datetime.now().strftime('%Y-%m-%d %H:%M')))
ov.append(('评估源文件', SRC))
ov.append(('审校模型', model_info or '（未记录）'))
ov.append(('评估模型', eval_info or '（未记录）'))
ov.append(('评估总行数', len(rows)))
ov.append(('（对照）训练集原始行数', 1500))
ov.append(('（说明）', '16条负样本在数据集转换时因内容重复被去除，未参与本次评估'))
ov.append(('', ''))
ov.append(('—— 官方指标（metrics）——', ''))
for k, v in metrics:
    ov.append((k, v))
ov.append(('', ''))
ov.append(('—— 错题统计 ——', ''))
ov.append(('FP误报', '%d行（%d处），其中%d行同时含TP（部分正确+多余误报）' % (len(fp_rows), fp_inst, fp_tp_cnt)))
ov.append(('FN漏报', '%d行，其中%d行同时含TP（部分正确+遗漏）' % (len(fn_rows), fn_tp_cnt)))
ov.append(('路由跳过·正样本', '%d行：判断题被 post_routing_filter 整体跳过，真实错误从未被审校' % len(skp_rows)))
ov.append(('评估解析失败', '%d行：评估模型未返回契约JSON（parse_fail），无法判定，未计入误报/漏报' % len(pf_rows)))
ov.append(('错题合计', '%d行 = FP误报%d + FN漏报%d + 跳过正样本%d + 解析失败%d%s' % (
    len(wrong), len(fp_rows), len(fn_rows), len(skp_rows), len(pf_rows),
    '（FP与FN重叠%d行已去重）' % fp_fn_overlap if fp_fn_overlap else '')))
ov.append(('路由跳过·负样本（参考）', '%d行：未审校但实际无错，不计入错题，见附表' % len(skn_rows)))
ov.append(('', ''))
ov.append(('—— 错题按 gold 错误类型分布 ——', ''))
for et in ['错别字', '选项结构错误', '题目与题型不一致']:
    sub = [r for r in wrong if r.get('error_type') == et]
    pos = sum(1 for r in sub if r.get('is_real_error') == 1)
    ov.append((et, '共%d行（正样本%d / 负样本%d）' % (len(sub), pos, len(sub) - pos)))
ov.append(('', ''))
ov.append(('—— FP行报错模式统计（按处数）——', ''))
for k, v in pat_counter.most_common():
    ov.append((k, '%d处' % v))
ov.append(('', ''))
ov.append(('—— 主要出错模式说明 ——', ''))
ov.append(('模式1：判断题路由过滤过激',
           'post_routing_filter 以"判断题待判陈述属于考点"为由整体跳过%d条判断题，其中%d条含真实错误从未审校，是漏报最大来源（模型本身漏报仅%d条）' % (
               len(skp_rows) + len(skn_rows), len(skp_rows), len(fn_rows))))
ov.append(('模式2：幻觉错别字', 'FP行中%d处"错字"的原文与修改完全相同（如 动摇→动摇、DSC→DSC）；全表另有30处同类输出混杂在被判TP的行内（与真实检出项并存），未计入误报' % halluc))
ov.append(('模式3：知识性改写当错别字', '把正确的术语改写当错字报出（己糖激酶→葡萄糖激酶、甾类激素→甾体激素、1000V→1000kV）'))
ov.append(('模式4：非选择题硬套选项结构检测', '名词解释/简答/论述/作文题被报"无法提取选项标号"类无意义错误'))
ov.append(('模式5：题型误判要求改写题面', '对正常题报题型不一致并要求改写（判断题→论述题、简答题→问答题）'))
ov.append(('模式6：选项标号序列苛求', '对合法的D/E/F起始编号或格式差异报"未按A开始连续排列"'))
ov.append(('', ''))
ov.append(('FN漏报题目ID', '、'.join(str(r.get('id')) for r in fn_rows)))
ov.append(('评估解析失败题目ID', '、'.join(str(r.get('id')) for r in pf_rows)))
ov.append(('缺失的16条评估行', 'TRAIN-V1.1-0190/0442/0457/0486/0560/0624/0662/0909/1007/1022/1119/1270/1388/1411/1471/1499（全为负样本，转换去重所致）'))
ov.append(('', ''))
ov.append(('—— 工作表说明 ——', ''))
ov.append(('全部错题', '%d行：所有审校出错题目全集，含完整题面/gold/模型输出，按出错分类着色，可筛选' % len(wrong)))
ov.append(('FP误报明细', '%d行' % len(fp_rows)))
ov.append(('FN漏报明细', '%d行' % len(fn_rows)))
ov.append(('路由跳过正样本', '%d行（实际漏报）' % len(skp_rows)))
ov.append(('评估解析失败', '%d行（无法判定）' % len(pf_rows)))
ov.append(('路由跳过负样本', '%d行（参考，不计错题）' % len(skn_rows)))

for i, (a, b) in enumerate(ov, 1):
    ca = ws1.cell(row=i, column=1, value=a)
    cb = ws1.cell(row=i, column=2, value=b)
    ca.alignment = Alignment(wrap_text=True, vertical='top')
    cb.alignment = Alignment(wrap_text=True, vertical='top')
    if a.startswith('——') or i == 1:
        ca.font = title_font if i == 1 else HDR_FONT
        if i != 1:
            cb.font = HDR_FONT
    elif a and b == '':
        pass
ws1.column_dimensions['A'].width = 36
ws1.column_dimensions['B'].width = 100

# ---------------- Sheet 2: 全部错题 ----------------
ws2 = out_wb.create_sheet('全部错题')
COLS_ALL = ['序号', '出错分类', 'id', '题目错误类型', 'is_real_error', 'gold错误数', '出错模式',
            'title', '题面(error_content)', 'gold_reason', 'gold标准错误(correction)',
            '模型has_error', '模型errors', '评估/跳过原因']
W_ALL = [6, 20, 18, 13, 8, 8, 30, 40, 60, 32, 45, 10, 45, 40]
write_header(ws2, COLS_ALL)

CAT_COLOR = {
    CAT_FP: 'FDE9E9', CAT_FPTP: 'FDE9E9',
    CAT_FN: 'FFF0DD', CAT_FNTP: 'FFF0DD',
    CAT_SKR_P: 'FFFBE6', CAT_PF_P: 'EFEFEF',
}
for i, r in enumerate(wrong, 2):
    vals = [
        i - 1, r['_cat'], r.get('id'), r.get('error_type'),
        r.get('is_real_error'), r.get('error_cnt'), pattern_note(r),
        str(r.get('title') or ''), str(r.get('error_content') or ''),
        str(r.get('gold_reason') or ''), errs_json(r.get('correction')),
        r.get('has_error') if r.get('has_error') is not None else '',
        errs_json(r.get('errors')), str(r.get('reason') or ''),
    ]
    fill = PatternFill(start_color=CAT_COLOR[r['_cat']], end_color=CAT_COLOR[r['_cat']], fill_type='solid')
    for c, v in enumerate(vals, 1):
        cell = set_cell(ws2, i, c, v)
        cell.fill = fill
set_widths(ws2, W_ALL)
ws2.freeze_panes = 'A2'
ws2.auto_filter.ref = 'A1:%s%d' % (get_column_letter(len(COLS_ALL)), len(wrong) + 1)

# ---------------- Sheet 3: FP误报明细 ----------------
ws3 = out_wb.create_sheet('FP误报明细')
COLS_FP = ['序号', 'id', 'gold错误类型', 'is_real_error', 'FP处数', '误报模式', '模型报错内容',
           'gold说明(gold_reason)', '题面摘要', '评估reason']
W_FP = [6, 18, 13, 8, 7, 32, 40, 30, 40, 45]
write_header(ws3, COLS_FP)
for i, r in enumerate(sorted(fp_rows, key=lambda x: (x.get('error_type') or '', str(x.get('id')))), 2):
    vals = [
        i - 1, r.get('id'), r.get('error_type'), r.get('is_real_error'),
        int(r.get('FP') or 0), '；'.join(classify_fp(parse_errors(r.get('errors')))),
        errs_brief(r.get('errors'), 200), str(r.get('gold_reason') or ''),
        str(r.get('error_content') or '')[:100].replace('\n', ' / '),
        str(r.get('reason') or ''),
    ]
    for c, v in enumerate(vals, 1):
        set_cell(ws3, i, c, v)
set_widths(ws3, W_FP)
ws3.freeze_panes = 'A2'
ws3.auto_filter.ref = 'A1:%s%d' % (get_column_letter(len(COLS_FP)), len(fp_rows) + 1)

# ---------------- Sheet 4: FN漏报明细 ----------------
ws4 = out_wb.create_sheet('FN漏报明细')
COLS_FN = ['序号', 'id', 'gold错误类型', 'gold错误数', 'gold错误内容', '模型has_error', '模型检出数',
           '模型报错内容', '题面摘要', '评估reason']
W_FN = [6, 18, 13, 8, 40, 10, 8, 40, 45, 45]
write_header(ws4, COLS_FN)
for i, r in enumerate(sorted(fn_rows, key=lambda x: str(x.get('id'))), 2):
    m = len(parse_errors(r.get('errors')))
    vals = [
        i - 1, r.get('id'), r.get('error_type'), r.get('error_cnt'),
        errs_brief(r.get('correction'), 200), str(r.get('has_error')), m,
        errs_brief(r.get('errors'), 200) or '（无）',
        str(r.get('error_content') or '')[:100].replace('\n', ' / '),
        str(r.get('reason') or ''),
    ]
    for c, v in enumerate(vals, 1):
        set_cell(ws4, i, c, v)
set_widths(ws4, W_FN)
ws4.freeze_panes = 'A2'
ws4.auto_filter.ref = 'A1:%s%d' % (get_column_letter(len(COLS_FN)), len(fn_rows) + 1)

# ---------------- Sheet 5: 路由跳过正样本 ----------------
ws5 = out_wb.create_sheet('路由跳过正样本')
COLS_SK = ['序号', 'id', 'gold错误类型', 'gold错误数', 'gold错误内容', '题面摘要', 'gold_reason', '跳过原因']
W_SK = [6, 18, 13, 8, 40, 45, 30, 40]
write_header(ws5, COLS_SK)
for i, r in enumerate(sorted(skp_rows, key=lambda x: str(x.get('id'))), 2):
    vals = [
        i - 1, r.get('id'), r.get('error_type'), r.get('error_cnt'),
        errs_brief(r.get('correction'), 200),
        str(r.get('error_content') or '')[:100].replace('\n', ' / '),
        str(r.get('gold_reason') or ''), str(r.get('reason') or ''),
    ]
    for c, v in enumerate(vals, 1):
        set_cell(ws5, i, c, v)
set_widths(ws5, W_SK)
ws5.freeze_panes = 'A2'
ws5.auto_filter.ref = 'A1:%s%d' % (get_column_letter(len(COLS_SK)), len(skp_rows) + 1)

# ---------------- Sheet 6: 评估解析失败 ----------------
ws6 = out_wb.create_sheet('评估解析失败')
COLS_PF = ['序号', 'id', 'gold错误类型', 'gold错误数', 'gold错误内容', '模型报错内容', '题面摘要', '评估reason']
W_PF = [6, 18, 13, 8, 40, 45, 45, 45]
write_header(ws6, COLS_PF)
for i, r in enumerate(sorted(pf_rows, key=lambda x: str(x.get('id'))), 2):
    vals = [
        i - 1, r.get('id'), r.get('error_type'), r.get('error_cnt'),
        errs_brief(r.get('correction'), 200), errs_brief(r.get('errors'), 200),
        str(r.get('error_content') or '')[:100].replace('\n', ' / '),
        str(r.get('reason') or ''),
    ]
    for c, v in enumerate(vals, 1):
        set_cell(ws6, i, c, v)
set_widths(ws6, W_PF)
ws6.freeze_panes = 'A2'

# ---------------- Sheet 7: 路由跳过负样本（参考） ----------------
ws7 = out_wb.create_sheet('路由跳过负样本')
COLS_SN = ['序号', 'id', '题目类型', '题面摘要', 'gold_reason', '跳过原因']
W_SN = [6, 18, 13, 50, 30, 40]
write_header(ws7, COLS_SN)
for i, r in enumerate(sorted(skn_rows, key=lambda x: str(x.get('id'))), 2):
    vals = [
        i - 1, r.get('id'), r.get('error_type'),
        str(r.get('error_content') or '')[:100].replace('\n', ' / '),
        str(r.get('gold_reason') or ''), str(r.get('reason') or ''),
    ]
    for c, v in enumerate(vals, 1):
        set_cell(ws7, i, c, v)
set_widths(ws7, W_SN)
ws7.freeze_panes = 'A2'
ws7.auto_filter.ref = 'A1:%s%d' % (get_column_letter(len(COLS_SN)), len(skn_rows) + 1)

out_wb.save(OUT)
print('已生成:', OUT)
print('错题合计 %d 行 = FP误报 %d 行(%d处,含TP共存%d行) + FN漏报 %d 行(含TP共存%d行) + 跳过正样本 %d 行 + 解析失败 %d 行' % (
    len(wrong), len(fp_rows), fp_inst, fp_tp_cnt, len(fn_rows), fn_tp_cnt, len(skp_rows), len(pf_rows)))
print('跳过负样本(参考): %d 行 | FP∩FN 重叠: %d 行' % (len(skn_rows), fp_fn_overlap))
print('幻觉错别字: %d 处 | 公式前缀防护触发: %d 单元格' % (halluc, GUARDED[0]))
print('FP模式分布:', dict(pat_counter))

# ---------------- 强制校验 ----------------
print()
print('========== 校验 ==========')
vb = load_workbook(OUT)
ok = True
expect = {'总览': None, '全部错题': len(wrong), 'FP误报明细': len(fp_rows), 'FN漏报明细': len(fn_rows),
          '路由跳过正样本': len(skp_rows), '评估解析失败': len(pf_rows), '路由跳过负样本': len(skn_rows)}
assert vb.sheetnames == list(expect.keys()), '工作表不符: %s' % vb.sheetnames
for name, n in expect.items():
    vws = vb[name]
    if n is None:
        print('[OK] %s: %d 行(概述表)' % (name, vws.max_row))
        continue
    data_rows = vws.max_row - 1
    status = 'OK' if data_rows == n else 'FAIL'
    if data_rows != n:
        ok = False
    print('[%s] %s: %d 数据行 (期望 %d)' % (status, name, data_rows, n))

w2 = vb['全部错题']
ids = [w2.cell(row=i, column=3).value for i in range(2, w2.max_row + 1)]
seq = [w2.cell(row=i, column=1).value for i in range(2, w2.max_row + 1)]
src_ids = set(str(r.get('id')) for r in rows)
c1 = len(ids) == len(set(ids))
c2 = seq == list(range(1, len(wrong) + 1))
c3 = all(str(x) in src_ids for x in ids)
for label, cond in [('id无重复', c1), ('序号1..N连续', c2), ('id均存在于源评估文件', c3)]:
    if not cond:
        ok = False
    print('[%s] %s' % ('OK' if cond else 'FAIL', label))

formula_cells = 0
for name in vb.sheetnames:
    for row in vb[name].iter_rows():
        for cell in row:
            if cell.data_type == 'f':
                formula_cells += 1
c4 = formula_cells == 0
if not c4:
    ok = False
print('[%s] 无公式单元格(防注入): %d 个公式单元格' % ('OK' if c4 else 'FAIL', formula_cells))

nums_ok = all(isinstance(w2.cell(row=i, column=5).value, (int, float)) and
              isinstance(w2.cell(row=i, column=6).value, (int, float))
              for i in range(2, w2.max_row + 1))
if not nums_ok:
    ok = False
print('[%s] is_real_error / gold错误数 均为数值' % ('OK' if nums_ok else 'FAIL'))
vb.close()
print('========== 校验结果: %s ==========' % ('全部通过' if ok else '存在失败项'))
