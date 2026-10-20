"""标点符号错误_训练集_v2.jsonl -> 完整数据集标点符号_v2.xlsx 转换脚本。

格式决策（用户跳过提问后采用的默认方案，均在最终汇报中说明）：
- correction：存完整 errors 数组的单行 JSON（标准答案零丢失）
- error_detailed_type：留空（JSONL 无此数据，不编造）
- model_name：沿用模板 Qwen3-Max-Preview
- corrected_content：填修复后的干净文本（语义正确）
- design_reason：按模板风格"本句包含N处错误：{descriptions}"
- content（正样本）：由 errors 最小差异反向修复重建；负样本 = detection_content
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from punct_repair import repair_all

from openpyxl import Workbook

JL = r'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集_v2.jsonl'
OUT = r'C:\hyt-agent\数据集\完整数据集标点符号_v2.xlsx'
TPL = r'C:\hyt-agent\数据集\完整数据集标点符号.xlsx'

COLUMNS = ['id', 'school', 'file_name', 'title', 'content', 'error_content',
           'error_cnt', 'error_type', 'error_detailed_type', 'correction',
           'design_reason', 'is_content_same', 'is_real_error', 'corrected_content',
           'model_name']


def parse_reference(ref):
    """从 reference 提取 (学科, 试卷标题去#号, 题型)。"""
    m_s = re.search(r'【学科】(.+)', ref)
    m_t = re.search(r'【试卷标题】(.+)', ref)
    m_q = re.search(r'【题型或其它信息】(.+)', ref)
    school = m_s.group(1).strip() if m_s else ''
    exam_title = m_t.group(1).strip().lstrip('#').strip() if m_t else ''
    file_name = exam_title + '.pdf' if exam_title else ''
    title = m_q.group(1).strip() if m_q else ''
    return school, file_name, title


def main():
    # 记录原始文件状态（保护验证用）
    jl_stat_before = os.stat(JL)
    tpl_stat_before = os.stat(TPL)

    records = []
    parse_fail = []
    with open(JL, 'r', encoding='utf-8') as f:
        for ln, line in enumerate(f, 1):
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
            try:
                payload = json.loads(user_c.split('[INPUT_PAYLOAD]', 1)[1].strip())
            except Exception as e:
                parse_fail.append((ln, f'payload: {e}'))
                continue
            try:
                a = json.loads(asst_c)
            except Exception as e:
                parse_fail.append((ln, f'assistant: {e}'))
                continue
            records.append({
                'ref': payload['reference'],
                'dc': payload['detection_content'],
                'a': a,
            })

    print(f'JSONL 解析: {len(records)} 条 | 解析失败 {len(parse_fail)}')
    if parse_fail:
        for ln, msg in parse_fail[:5]:
            print(f'  行{ln}: {msg}')
        raise SystemExit('存在解析失败，终止')

    # 逐条转换
    wb = Workbook()
    ws = wb.active
    ws.title = 'Sheet1'
    ws.append(COLUMNS)

    n_pos = n_neg = 0
    repair_fails = []
    for i, rec in enumerate(records, 1):
        a = rec['a']
        school, file_name, title = parse_reference(rec['ref'])
        has_error = bool(a.get('has_error'))
        errs = a.get('errors', [])
        total = a.get('total_errors', 0)

        if has_error:
            n_pos += 1
            content, hows = repair_all(rec['dc'], errs)
            if content is None:
                repair_fails.append(i)
                content = rec['dc']  # 兜底：重建失败时退化为 dc（不应发生，前面已验证 580/580）
            correction = json.dumps(errs, ensure_ascii=False)
            design_reason = f'本句包含{total}处错误：' + '；'.join(
                str(e.get('description', '')).strip() for e in errs)
            corrected_content = content
            is_content_same = False
            error_cnt = int(total)
        else:
            n_neg += 1
            content = rec['dc']
            correction = None
            design_reason = None
            corrected_content = None
            is_content_same = True
            error_cnt = 0

        ws.append([
            i,                    # id: int
            school,               # school
            file_name,            # file_name
            title,                # title
            content,              # content（干净原文）
            rec['dc'],            # error_content（含错误，原样）
            error_cnt,            # error_cnt: int
            '标点符号错误',        # error_type
            None,                 # error_detailed_type（JSONL无此数据）
            correction,           # correction: errors JSON
            design_reason,        # design_reason
            is_content_same,      # is_content_same: bool
            has_error,            # is_real_error: bool
            corrected_content,    # corrected_content
            'Qwen3-Max-Preview',  # model_name
        ])

    wb.save(OUT)
    print(f'已写入: {OUT}')
    print(f'有错 {n_pos} | 无错 {n_neg} | content 重建失败 {len(repair_fails)}')

    # 原始文件保护验证
    jl_stat_after = os.stat(JL)
    tpl_stat_after = os.stat(TPL)
    assert jl_stat_before.st_size == jl_stat_after.st_size and int(jl_stat_before.st_mtime) == int(jl_stat_after.st_mtime), 'JSONL 被意外修改!'
    assert tpl_stat_before.st_size == tpl_stat_after.st_size and int(tpl_stat_before.st_mtime) == int(tpl_stat_after.st_mtime), '模板被意外修改!'
    print('原始文件未被修改 ✓')


if __name__ == '__main__':
    main()
