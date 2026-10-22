# 独立开发阶段的组卷题库约定

用户确认：先独立开发，最后整合；题库视为已经筛选完成，每题必有答案。选项原文标识由组卷侧先自定义。
本约定优先于 INTERFACE_CONTRACT.md 中关于独立开发阶段的待定事项；不擅自改变审校同学的服务。

## 模拟已筛选题库

唯一默认题库为 examples/question_bank.json：20 道数据结构单选题，线性表、栈、队列、树、图各 4 题。
每类含简单 1 题、中等 2 题、困难 1 题，每题 2 分，均有四选项、答案字母和解析。
review.status=PASS 且 review.is_mock=true 表示模拟“已筛选”，并非真实审校服务通过。
难度仅为开发标签。不可将开发库直接当作正式评测集。

## 内部格式

- options 使用对象：{"A":"选项内容","B":"选项内容","C":"选项内容","D":"选项内容"}。
- 标识固定 A-D；内容不重复存 A. 等前缀，渲染时统一生成。
- answer 必须是 A/B/C/D 中一个有效键；空答案不能入选，不由组卷临时求解或猜测。
- 保持选项顺序，不随机打乱；以后如需打乱，必须同步重映射答案。
- question_id 与 version 标识来源及版本；学生卷重新编号 1-N，答案沿用同次编号。
- 当前只支持一个科目、单选题、整数分值和一个主知识点的配额；多科目、多题型后续扩展。

## 输出

成功组卷后输出两个独立可阅读文档：student_exam.html 和 answer_key.html。
学生卷包含标题、总分、题数、姓名栏、作答说明、连续题号、分值、题干和 A-D 选项；不包含答案解析。
答案卷包含对应题号、正确选项字母/内容、解析和来源题号，仅供教师使用。
同时保留 JSON、检查报告和换题轨迹。report.json 含答案信息，不作为学生试卷分发。
HTML 无额外依赖，可用浏览器打开/打印。可选 --pdf 生成同名 PDF，需要 reportlab。
Pi 工具成功时也导出 HTML，export_pdf=true 时另输出 PDF；均返回绝对文件路径。
输出失败或未通过检查时不宣称有最终试卷；成功状态仍是 STRUCTURAL_PASS，不代表语义检查已实现。

## 本地运行（在 github-upload 仓库根目录）

```powershell
python exam_assembly_agent/main.py --output-dir exam_assembly_agent/outputs/complete_exam_1
```

可选 PDF：

```powershell
python -m pip install -r exam_assembly_agent/requirements-pdf.txt
python exam_assembly_agent/main.py --output-dir exam_assembly_agent/outputs/complete_exam_pdf_1 --pdf
```

每次用新目录，防止旧试卷与新答案混用。后续开发统一在 github-upload 中进行，不再回写原目录。
