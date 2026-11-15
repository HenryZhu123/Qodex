"""One self-authored answered fixture; never changes the original source PDF."""
from pathlib import Path
import subprocess
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

root = Path(__file__).resolve().parents[1]
output = root / "output/pdf/qodex-answer-included-test.pdf"
output.parent.mkdir(parents=True, exist_ok=True)
assert not output.exists(), "Preserve the existing fixture instead of overwriting"
pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
doc = canvas.Canvas(str(output))
doc.setTitle("Qodex 有答案测试卷")
lines = [
    (20, "数据结构联调测试卷（含标准答案）"),
    (11, "本卷为自行编写的接口测试题。单项选择题，共 1 题，每题 2 分。"),
    (14, "一、单项选择题"),
    (12, "1. 一个初始为空的栈依次执行 push(1)、push(2)、pop()、push(3)。"),
    (12, "此时栈顶元素是（    ）。（2 分）"),
    (12, "A. 1"), (12, "B. 2"), (12, "C. 3"), (12, "D. 栈为空"),
    (15, "标准答案与解析"), (12, "第 1 题：C。"),
    (12, "解析：栈后进先出。弹出 2 后压入 3，因此栈顶元素为 3。"),
]
y = 780
for size, line in lines:
    doc.setFont("STSong-Light", size)
    doc.drawString(55, y, line)
    y -= 42 if size > 14 else 32
doc.save()
subprocess.run(["pdftoppm", "-scale-to", "1400", "-png", "-singlefile", str(output), str(root / ".local/answered-smoke-preview")], check=True)
print("Answered fixture created and rendered.")
