"""v2 JSONL -> XLSX 转换：核心是正样本干净原文重建算法（最小差异 + anchor 定位）。"""
import json

def minimal_diff(a, b):
    """返回 (p, om, cm)：a = 前缀 + om + 后缀, b = 前缀 + cm + 后缀，差异最小化。"""
    p = 0
    while p < min(len(a), len(b)) and a[p] == b[p]:
        p += 1
    s = 0
    while s < min(len(a), len(b)) - p and a[len(a) - 1 - s] == b[len(b) - 1 - s]:
        s += 1
    return p, a[p:len(a) - s], b[p:len(b) - s]


def locate(dc, ot, at):
    """在 dc 中定位 ot 的起始位置：anchor 优先，其次全文首次出现。返回 (start, how)。"""
    if at:
        ai = dc.find(at)
        if ai >= 0:
            rel = at.find(ot)
            if rel >= 0:
                return ai + rel, 'anchor'
    i = dc.find(ot)
    if i >= 0:
        return i, 'direct'
    return -1, 'fail'


def repair(dc, err):
    """用单个 error 项修复 dc，返回 (修复后文本, 方式说明)。"""
    ot = str(err.get('original_text', ''))
    co = str(err.get('correction', ''))
    at = str(err.get('anchor_text', ''))
    if ot == co:
        return dc, 'nochange'
    p, om, cm = minimal_diff(ot, co)
    if om == '' and cm == '':
        return dc, 'nochange'
    # 定位整个 original_text
    st, how = locate(dc, ot, at)
    if st >= 0:
        # om 在 ot 内的位置即 p
        abs_start = st + p
        if dc[abs_start:abs_start + len(om)] == om:
            return dc[:abs_start] + cm + dc[abs_start + len(om):], how
        # om 不在预期位置（原文与dc不一致），退化处理
    # 退化1：直接定位 om
    if om:
        st2, how2 = locate(dc, om, at)
        if st2 >= 0 and dc[st2:st2 + len(om)] == om:
            return dc[:st2] + cm + dc[st2 + len(om):], 'minimal-' + how2
    # 退化2：纯插入/删除时用前后文定位
    return None, 'fail'


def inject(clean, err):
    """正向注入：在干净文本上应用错误，应还原出带错文本。与 repair 对称。"""
    ot = str(err.get('original_text', ''))
    co = str(err.get('correction', ''))
    at = str(err.get('anchor_text', ''))
    if ot == co:
        return clean
    p, om, cm = minimal_diff(ot, co)
    if om == '' and cm == '':
        return clean

    def try_at(seg_start):
        """在 clean 的 seg_start 处应为 co，替换其中的 cm -> om。"""
        if clean[seg_start:seg_start + len(co)] == co:
            abs_start = seg_start + p
            if clean[abs_start:abs_start + len(cm)] == cm:
                return clean[:abs_start] + om + clean[abs_start + len(cm):]
        return None

    # 优先 anchor：at = A + ot + B（A/B 为干净上下文），clean 中对应 A + co + B
    if at:
        rel = at.find(ot)
        if rel >= 0:
            A, B = at[:rel], at[rel + len(ot):]
            if A:
                pa = clean.find(A)
                if pa >= 0:
                    r = try_at(pa + len(A))
                    if r is not None:
                        return r
            if B:
                pb = clean.find(B)
                if pb >= 0:
                    r = try_at(pb - len(co))
                    if r is not None:
                        return r
    # 退化：直接找 co（cm 非空时可定位；co 为空的纯删除无锚点时无法定位）
    if co:
        st = clean.find(co)
        if st >= 0:
            r = try_at(st)
            if r is not None:
                return r
    return None


def repair_all(dc, errs):
    """依次应用所有 error 修复。返回 (文本, [方式列表])。"""
    out = dc
    hows = []
    for e in errs:
        out, how = repair(out, e)
        if out is None:
            return None, hows + ['fail']
        hows.append(how)
    return out, hows


if __name__ == '__main__':
    # 用 v2 数据自测：580 正样本全部跑一遍，统计成功率
    JL = r'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集_v2.jsonl'
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

    pos = [j for j in jl if j['a']['has_error']]
    ok = fail = 0
    from collections import Counter
    hows = Counter()
    fails = []
    for j in pos:
        out, h = repair_all(j['dc'], j['a']['errors'])
        if out is None:
            fail += 1
            fails.append(j)
        else:
            ok += 1
            hows.update(h)
    print(f'正样本 content 重建: 成功 {ok}/580 | 失败 {fail}')
    print('定位方式分布:', dict(hows))
    for j in fails[:5]:
        e = j['a']['errors'][0]
        print('失败案例 dc:', j['dc'][:60])
        print('  ot:', repr(e['original_text'][:60]), '| co:', repr(e['correction'][:60]), '| at:', repr(e['anchor_text'][:60]))
