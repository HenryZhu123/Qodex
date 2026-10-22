"""独立学生卷和答案导出。HTML 无依赖；PDF 使用可选 reportlab。"""
from html import escape
import os
from pathlib import Path


def export_exam(request, result, output_dir, *, pdf=False):
    if result.get("status") != "STRUCTURAL_PASS":
        raise ValueError("仅允许导出检查通过的候选卷")
    questions = result["student_exam"]
    answers = {a["question_id"]: a for a in result["answer_key"]}
    if len(answers) != len(questions) or set(answers) != {q["question_id"] for q in questions}:
        raise ValueError("试卷与答案题目不一致")
    for q in questions:
        if answers[q["question_id"]].get("answer") not in q["options"]:
            raise ValueError("题目缺少有效答案，不能导出完整试卷包")
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    e = lambda value: escape(str(value))
    title = f'{request["subject"]}练习试卷'
    notice = '模拟已筛选题库开发演示；非真实审校验收结果，难度标签未经校准。' if result.get("uses_mock_reviews") else '请按试卷说明作答。'
    meta = f'共 {len(questions)} 题 / 满分 {request["total_score"]} 分 / 单项选择题'
    student, teacher = [], []
    for number, q in enumerate(questions, 1):
        a = answers[q["question_id"]]
        student.append(f'<section class="question"><h2>{number}.（{e(q["score"])} 分）</h2>'
                       f'<div class="text">{e(q["stem"])}</div><ol class="options">' +
                       ''.join(f'<li><span>{label}.</span> {e(q["options"][label])}</li>' for label in 'ABCD') + '</ol></section>')
        teacher.append(f'<section class="question"><h2>第 {number} 题：{e(a["answer"])}（{e(q["score"])} 分）</h2>'
                       f'<p>正确选项：{e(q["options"][a["answer"]])}</p>'
                       f'<div class="text">解析：{e(a.get("explanation") or "未提供解析")}</div>'
                       f'<p class="muted">来源题号：{e(q["question_id"])}</p></section>')
    style = '''body{font-family:"Microsoft YaHei",sans-serif;max-width:760px;margin:36px auto;padding:0 22px;color:#182634;line-height:1.65}h1{font-size:25px}h2{font-size:16px;margin-bottom:6px}.meta,.muted{color:#586574;font-size:13px}.notice{border-left:3px solid #627d98;padding:8px 12px;background:#f2f5f8;font-size:13px}.question{margin:22px 0;break-inside:avoid}.options{padding:0;list-style:none}.options li{margin:4px 0 4px 18px}.text{white-space:pre-wrap}.muted{font-size:11px}header{border-bottom:1px solid #ccd5df;padding-bottom:16px}@page{size:A4;margin:18mm}@media print{body{margin:0;padding:0;max-width:none}.notice{background:none}}'''
    paths = {}
    for name, heading, content, identity in (
            ('student_exam', title, student, '<p>姓名：____________　班级：____________　学号：____________</p><p>每题只有一个正确选项，请从 A、B、C、D 中选择。</p>'),
            ('answer_key', title + ' - 答案与解析', teacher, '<p>教师用答案，请与同次生成的学生卷配套使用。</p>')):
        page = f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>{e(heading)}</title><style>{style}</style><body><header><h1>{e(heading)}</h1><div class="meta">{e(meta)} / 试卷编号：{e(request.get("request_id", ""))}</div>{identity}<div class="notice">{e(notice)}</div></header>{"".join(content)}</body></html>'
        path = folder / f'{name}.html'
        path.write_text(page, encoding='utf-8')
        paths[name + '_html'] = str(path.resolve())
    if pdf:
        paths.update(_export_pdf(request, result, folder, title, meta, notice))
    return paths


def _export_pdf(request, result, folder, title, meta, notice):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether

    font_path = os.getenv('QODEX_CJK_FONT', 'C:/Windows/Fonts/simsun.ttc')
    if Path(font_path).is_file():
        if 'QodexChinese' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('QodexChinese', font_path, subfontIndex=0))
        font = 'QodexChinese'
    else:
        font = 'STSong-Light'
        if font not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont(font))
    body = ParagraphStyle('Body', fontName=font, fontSize=11, leading=16, wordWrap='CJK', spaceAfter=4)
    heading = ParagraphStyle('Heading', parent=body, fontSize=20, leading=28, alignment=TA_CENTER, spaceAfter=12)
    small = ParagraphStyle('Small', parent=body, fontSize=9, leading=14, textColor=colors.HexColor('#536273'))
    def p(text, style=body):
        return Paragraph(escape(str(text)).replace('\n', '<br/>'), style)
    def footer(canvas, doc):
        canvas.setFont(font, 9)
        canvas.setFillColor(colors.HexColor('#536273'))
        canvas.drawString(48, 28, 'Qodex / ' + str(request.get('request_id', '')))
        canvas.drawRightString(547, 28, f'第 {doc.page} 页')
    answers = {a['question_id']: a for a in result['answer_key']}
    paths = {}
    for is_answer, name in ((False, 'student_exam'), (True, 'answer_key')):
        story = [p(title + (' - 答案与解析' if is_answer else ''), heading), p(meta, small), p(notice, small), Spacer(1, 12)]
        if not is_answer:
            story += [p('姓名：____________　班级：____________　学号：____________'), p('每题只有一个正确选项，请从 A、B、C、D 中选择。'), Spacer(1, 8)]
        for number, q in enumerate(result['student_exam'], 1):
            if is_answer:
                a = answers[q['question_id']]
                block = [p(f'第 {number} 题：{a["answer"]}（{q["score"]} 分）'),
                         p('正确选项：' + q['options'][a['answer']]),
                         p('解析：' + (a.get('explanation') or '未提供解析')),
                         p('来源题号：' + q['question_id'], small)]
            else:
                block = [p(f'{number}.（{q["score"]} 分）' + q['stem'])]
                block += [p(f'{label}. {q["options"][label]}') for label in 'ABCD']
            story += [KeepTogether(block), Spacer(1, 13)]
        path = folder / f'{name}.pdf'
        SimpleDocTemplate(str(path), pagesize=(595.28, 841.89), leftMargin=48, rightMargin=48,
                          topMargin=44, bottomMargin=46, title=title, author='Qodex development demo').build(
                              story, onFirstPage=footer, onLaterPages=footer)
        paths[name + '_pdf'] = str(path.resolve())
    return paths
