# -*- coding: utf-8 -*-
"""
将 test_v1.1.jsonl 转换为 test_v1.1_测试集.xlsx
规则严格遵循需求文档，生成后进行全量校验。
"""
import json
import re
import sys
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

INPUT_PATH = r'C:\hyt-agent\测试集\test_v1.1.jsonl'
OUTPUT_PATH = r'C:\hyt-agent\测试集\test_v1.1_测试集.xlsx'

COLUMNS = ['id', 'title', 'error_content', 'error_type', 'correction',
           'error_cnt', 'is_real_error', 'gold_reason']

# 任务名 -> error_type 映射（选项结构错误统一为选项错误）
TASK_TO_TYPE = {
    '错别字': '错别字',
    '选项结构错误': '选项错误',
    '题目与题型不一致': '题目与题型不一致',
}
ALLOWED_TYPES = {'错别字', '选项错误', '题目与题型不一致'}

# 防公式注入：Excel 会把这些开头的单元格当作公式
DANGEROUS_PREFIXES = ('=', '+', '-', '@')


def parse_user_payload(user_content):
    """从 user 消息中解析 [INPUT_PAYLOAD] 后的 JSON"""
    # 找到第一个 { 和最后一个 }
    start = user_content.find('{')
    end = user_content.rfind('}')
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f'无法解析 user payload: {user_content[:100]}')
    return json.loads(user_content[start:end + 1])


def extract_task_name(system_content):
    """从 system 消息中提取 # 任务：xxx"""
    m = re.search(r'# 任务：(.+?)$', system_content, re.MULTILINE)
    if not m:
        raise ValueError('system 消息中未找到 # 任务：')
    return m.group(1).strip()


def parse_assistant_output(assistant_content):
    """解析 assistant 标准答案 JSON"""
    return json.loads(assistant_content)


def set_text_cell(ws, row, col, value):
    """写入文本单元格并强制按文本存储，防止公式注入"""
    cell = ws.cell(row=row, column=col, value=value)
    if isinstance(value, str) and value.startswith(DANGEROUS_PREFIXES):
        cell.data_type = 's'
    return cell


def main():
    rows = []
    with open(INPUT_PATH, 'r', encoding='utf-8') as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            msgs = {m['role']: m['content'] for m in data['messages']}

            system_content = msgs['system']
            user_content = msgs['user']
            assistant_content = msgs['assistant']

            # 1. id（从 1 连续编号，延迟到写表时）
            # 2. title / error_content
            user_payload = parse_user_payload(user_content)
            title = user_payload['reference']
            error_content = user_payload['detection_content']

            # 3. error_type
            task_name = extract_task_name(system_content)
            if task_name not in TASK_TO_TYPE:
                raise ValueError(f'未知任务类型: {task_name}')
            error_type = TASK_TO_TYPE[task_name]

            # 4. assistant 解析
            asst = parse_assistant_output(assistant_content)
            reason = asst.get('reason', '')
            has_error = bool(asst.get('has_error', False))
            total_errors = asst.get('total_errors', 0)
            errors = asst.get('errors', [])

            # 5. correction：has_error=true 时序列化 errors 数组；否则空
            if has_error:
                correction = json.dumps(errors, ensure_ascii=False, separators=(',', ':'))
            else:
                correction = ''

            # 6. error_cnt / is_real_error
            error_cnt = int(total_errors) if has_error else 0
            is_real_error = 1 if has_error else 0

            rows.append({
                'title': title,
                'error_content': error_content,
                'error_type': error_type,
                'correction': correction,
                'error_cnt': error_cnt,
                'is_real_error': is_real_error,
                'gold_reason': reason,
                # 原始行号，用于校验
                '_src_line': idx + 1,
                '_asst_has_error': has_error,
                '_asst_total_errors': total_errors,
                '_asst_errors_len': len(errors),
            })

    # 校验 total_errors 与 errors 长度一致性（仅为发现异常）
    for r in rows:
        if r['_asst_has_error']:
            if r['_asst_total_errors'] != r['_asst_errors_len']:
                print(f'WARNING 行{ r["_src_line"] }: total_errors={r["_asst_total_errors"]} != len(errors)={r["_asst_errors_len"]}', file=sys.stderr)

    # 写 Excel
    wb = Workbook()
    ws = wb.active
    ws.title = '测试集'

    # 表头
    header_font = Font(bold=True, size=11)
    header_fill = PatternFill(start_color='DDEBF7', end_color='DDEBF7', fill_type='solid')
    for col, name in enumerate(COLUMNS, start=1):
        c = ws.cell(row=1, column=col, value=name)
        c.font = header_font
        c.fill = header_fill
        c.alignment = Alignment(vertical='center')

    wrap_columns = {2, 3, 5, 8}  # title, error_content, correction, gold_reason

    for i, r in enumerate(rows):
        row_num = i + 2
        ws.cell(row=row_num, column=1, value=i + 1)  # id 连续整数
        set_text_cell(ws, row_num, 2, r['title'])
        set_text_cell(ws, row_num, 3, r['error_content'])
        set_text_cell(ws, row_num, 4, r['error_type'])
        set_text_cell(ws, row_num, 5, r['correction'])
        ws.cell(row=row_num, column=6, value=r['error_cnt'])  # 数值
        ws.cell(row=row_num, column=7, value=r['is_real_error'])  # 数值
        set_text_cell(ws, row_num, 8, r['gold_reason'])

        for col in wrap_columns:
            ws.cell(row=row_num, column=col).alignment = Alignment(
                wrap_text=True, vertical='top')

    # 冻结首行
    ws.freeze_panes = 'A2'
    # 自动筛选
    ws.auto_filter.ref = f'A1:{get_column_letter(len(COLUMNS))}{len(rows) + 1}'

    # 合理列宽
    widths = {1: 8, 2: 50, 3: 60, 4: 18, 5: 50, 6: 10, 7: 12, 8: 40}
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w

    wb.save(OUTPUT_PATH)
    print(f'已生成: {OUTPUT_PATH}')
    print(f'数据行数: {len(rows)}')

    # 保存中间 rows 供校验用
    with open(r'C:\hyt-agent\scripts\_rows_cache.json', 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False)
    return rows


if __name__ == '__main__':
    main()
