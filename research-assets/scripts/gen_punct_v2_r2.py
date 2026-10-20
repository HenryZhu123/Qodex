"""标点符号错误_训练集_v2.jsonl -> 完整数据集标点符号_v2.xlsx 重新生成（规则 v2 正式版）。

用户新规则（本版执行）：
1. correction    = 完整 errors 数组紧凑 JSON（7 字段全保留），无错题 '[]'
2. error_detailed_type = 错误类型索引.jsonl 的 error_subtype（training_line 与 JSONL 行号一一对应），无错题留空
3. model_name    = 来源清单映射：Qwen3.8-max_审核通过 -> Qwen3.8-max；Codex_* -> Codex；其余 Qwen3-Max-Preview
4. corrected_content = 按完整 errors 以 anchor_text 定位 original_text 并替换为 correction；
                      无法可靠定位/多处匹配不得猜测 -> 记录为转换失败并在报告中列出

严格性要点：
- anchor 在题干中必须唯一；
- anchor 内 original_text 唯一时直接用；
- anchor 内 original_text 多次出现（13 条，均为逗号）时，取锚点内最后一个候选，
  并按错误描述语义校验（co='。' -> 后接选项/空白括号/换行；co='：' -> 前接提示语），
  语义校验不过即失败；correction 与 description 矛盾（疑似损坏）即失败。
- 修复后验证：错误片段计数减少 1（correction 本身含该片段时跳过计数校验）。

不修改任何原 JSONL / 模板 XLSX；基于模板写入以保留 15 列、列名、顺序、Sheet1 与样式。
"""
import json
import os
import re
import sys

from openpyxl import load_workbook

JL = r'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集_v2.jsonl'
IDX = r'C:\hyt-agent\训练集-微调版提示词\标点符号错误_v2_关键文件\标点符号错误_训练集_v2_错误类型索引.jsonl'
SRC = r'C:\hyt-agent\训练集-微调版提示词\标点符号错误_v2_关键文件\标点符号错误_训练集_v2_标准答案来源清单.jsonl'
TPL = r'C:\hyt-agent\数据集\完整数据集标点符号.xlsx'
OUT = r'C:\hyt-agent\数据集\完整数据集标点符号_v2.xlsx'

COLUMNS = ['id', 'school', 'file_name', 'title', 'content', 'error_content',
           'error_cnt', 'error_type', 'error_detailed_type', 'correction',
           'design_reason', 'is_content_same', 'is_real_error', 'corrected_content',
           'model_name']

PROMPT_KWS = ('求证', '回答以下问题', '协议规定')


def minimal_diff(a, b):
    """返回 (p, om, cm)：a = 前缀 + om + 后缀, b = 前缀 + cm + 后缀。"""
    p = 0
    while p < min(len(a), len(b)) and a[p] == b[p]:
        p += 1
    s = 0
    while s < min(len(a), len(b)) - p and a[len(a) - 1 - s] == b[len(b) - 1 - s]:
        s += 1
    return p, a[p:len(a) - s], b[p:len(b) - s]


def parse_reference(ref):
    """从 reference 提取 (school, file_name, title)。"""
    m_s = re.search(r'【学科】(.+)', ref)
    m_t = re.search(r'【试卷标题】(.+)', ref)
    m_q = re.search(r'【题型或其它信息】(.+)', ref)
    school = m_s.group(1).strip() if m_s else ''
    exam_title = m_t.group(1).strip().lstrip('#').strip() if m_t else ''
    file_name = exam_title + '.pdf' if exam_title else ''
    title = m_q.group(1).strip() if m_q else ''
    return school, file_name, title


def repair_strict(dc, err):
    """严格修复单条错误。返回 (out_text, how, ok)。
    失败时 out_text 为 None，how 为失败原因。绝不猜测。"""
    ot = str(err.get('original_text', ''))
    co = str(err.get('correction', ''))
    at = str(err.get('anchor_text', ''))
    if not ot:
        return None, 'empty_original_text', False
    if ot == co:
        return dc, 'nochange', True
    p, om, cm = minimal_diff(ot, co)
    if om == '' and cm == '':
        return dc, 'nochange', True

    ai = dc.find(at) if at else -1
    if ai < 0:
        # anchor 不在题干中：退化为 ot 唯一性直接定位
        if dc.count(ot) != 1:
            return None, 'anchor_not_found_direct_ambiguous', False
        ap = dc.find(ot)
        how = 'direct'
    else:
        if dc.count(at) != 1:
            return None, 'anchor_ambiguous', False
        rels = [k for k in range(len(at)) if at.startswith(ot, k)]
        if not rels:
            # anchor 存在但未含 ot：退化为 ot 唯一性直接定位
            if dc.count(ot) != 1:
                return None, 'ot_not_in_anchor_direct_ambiguous', False
            ap = dc.find(ot)
            how = 'direct'
        elif len(rels) == 1:
            ap = ai + rels[0]
            how = 'anchor'
        else:
            # 锚点内 ot 多次出现：取最后一个候选并做语义校验
            rel = rels[-1]
            ap = ai + rel
            if co == '。':
                after = dc[ap + len(ot):].lstrip()
                if after and after[0] not in 'A（(':
                    return None, 'ambiguous_semantic_fail', False
            elif co == '：':
                before = dc[max(0, ap - 15):ap]
                if not any(before.endswith(kw) for kw in PROMPT_KWS):
                    return None, 'ambiguous_semantic_fail', False
            else:
                return None, 'co_broken', False
            how = 'anchor-last'

    abs_start = ap + p
    if dc[abs_start:abs_start + len(om)] != om:
        return None, 'mismatch', False
    out = dc[:abs_start] + cm + dc[abs_start + len(om):]

    # 验证错误片段已消除：计数应减少恰好 1（correction 本身含 ot 时无法计数，跳过）
    if ot not in co:
        if out.count(ot) != dc.count(ot) - 1:
            return None, 'fragment_still_present', False
    return out, how, True


def main():
    jl_before = os.stat(JL)
    tpl_before = os.stat(TPL)

    # ---- 读取映射文件 ----
    idx_map = {}
    with open(IDX, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            idx_map[int(r['training_line'])] = r['error_subtype']
    src_map = {}
    with open(SRC, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            src_map[int(r['training_line'])] = r['answer_origin']
    print(f'索引映射 {len(idx_map)} 条 | 来源映射 {len(src_map)} 条')

    def model_name_for(tl):
        origin = src_map.get(tl)
        if origin == 'Qwen3.8-max_审核通过':
            return 'Qwen3.8-max'
        if origin and origin.startswith('Codex_'):
            return 'Codex'
        return 'Qwen3-Max-Preview'

    # ---- 解析 JSONL ----
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
            records.append({'ref': payload['reference'], 'dc': payload['detection_content'], 'a': a})
    if parse_fail:
        for ln, msg in parse_fail[:5]:
            print(f'  行{ln}: {msg}')
        raise SystemExit('存在解析失败，终止')
    print(f'JSONL 解析: {len(records)} 条')

    # ---- 基于模板写入（保留样式） ----
    wb = load_workbook(TPL)
    ws = wb.active
    assert ws.max_column == 15 and wb.sheetnames == ['Sheet1'], '模板结构不符'
    headers = [ws.cell(1, c).value for c in range(1, 16)]
    assert headers == COLUMNS, f'模板表头不符: {headers}'

    failures = []          # (行号, 列, 原因)
    n_pos = n_neg = 0
    for i, rec in enumerate(records, 1):
        a = rec['a']
        school, file_name, title = parse_reference(rec['ref'])
        has_error = bool(a.get('has_error'))
        errs = a.get('errors', [])
        total = int(a.get('total_errors', len(errs)))

        # correction 列：完整 errors JSON / '[]'
        correction = json.dumps(errs, ensure_ascii=False, separators=(',', ':')) if has_error else '[]'
        # error_detailed_type 列
        detailed = idx_map.get(i, '') if has_error else ''
        if has_error and i not in idx_map:
            failures.append((i, 'error_detailed_type', '索引缺失'))
        # model_name 列
        model_name = model_name_for(i)

        if has_error:
            n_pos += 1
            if not errs:
                failures.append((i, 'errors', 'has_error 但 errors 为空'))
                content = corrected = ''
                design_reason = None
            else:
                out, how, ok = repair_strict(rec['dc'], errs[0])
                if not ok:
                    failures.append((i, 'corrected_content', how))
                    content = corrected = ''
                else:
                    content = corrected = out
                design_reason = f'本句包含{total}处错误：' + '；'.join(
                    str(e.get('description', '')).strip() for e in errs)
            error_cnt = total
            is_same = False
            real = True
        else:
            n_neg += 1
            content = corrected = rec['dc']
            design_reason = None
            error_cnt = 0
            is_same = True
            real = False

        ws.cell(i + 1, 1, i)
        ws.cell(i + 1, 2, school)
        ws.cell(i + 1, 3, file_name)
        ws.cell(i + 1, 4, title)
        ws.cell(i + 1, 5, content)
        ws.cell(i + 1, 6, rec['dc'])
        ws.cell(i + 1, 7, error_cnt)
        ws.cell(i + 1, 8, '标点符号错误')
        ws.cell(i + 1, 9, detailed if detailed else None)
        ws.cell(i + 1, 10, correction)
        ws.cell(i + 1, 11, design_reason)
        ws.cell(i + 1, 12, is_same)
        ws.cell(i + 1, 13, real)
        ws.cell(i + 1, 14, corrected)
        ws.cell(i + 1, 15, model_name)

    wb.save(OUT)
    print(f'已写入: {OUT}')
    print(f'有错 {n_pos} | 无错 {n_neg} | 转换失败 {len(failures)}')
    for tl, col, why in failures:
        print(f'  [失败] 行{tl} | {col} | {why}')

    # ---- 原始文件保护验证 ----
    jl_after = os.stat(JL)
    tpl_after = os.stat(TPL)
    assert jl_before.st_size == jl_after.st_size and int(jl_before.st_mtime) == int(jl_after.st_mtime), 'JSONL 被意外修改!'
    assert tpl_before.st_size == tpl_after.st_size and int(tpl_before.st_mtime) == int(tpl_after.st_mtime), '模板被意外修改!'
    print('原始文件未被修改 OK')
    return failures


if __name__ == '__main__':
    main()
