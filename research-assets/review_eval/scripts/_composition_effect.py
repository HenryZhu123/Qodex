import json
from collections import defaultdict

DEV_B = "hku_agent/research-assets/review_eval/blind_test_set/runs/blind_evaluation/blind_results.jsonl"
V2 = "hku_agent/research-assets/review_eval/blind_test_v2/runs/frozen_eval/v2_results.jsonl"


def load(path):
    recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    st = defaultdict(lambda: [0, 0])
    for r in recs:
        c = r["category"]
        st[c][0] += 1
        if r["has_error"]:
            st[c][1] += 1
    return dict(st)


devb = load(DEV_B)
v2 = load(V2)

cats = sorted(set(devb) | set(v2))
print(f"{'class':<18}{'DevB n':>8}{'DevB R%':>9}{'v2 n':>7}{'v2 R%':>8}{'delta pp':>10}")
for c in cats:
    n1, h1 = devb.get(c, [0, 0])
    n2, h2 = v2.get(c, [0, 0])
    r1 = h1 / n1 * 100 if n1 else float("nan")
    r2 = h2 / n2 * 100 if n2 else float("nan")
    print(f"{c:<18}{n1:>8}{r1:>9.1f}{n2:>7}{r2:>8.1f}{r2 - r1:>+10.1f}")

err_cats = [c for c in cats if c != "clean"]

# macro (unweighted average over error classes)
macro_b = sum(devb[c][1] / devb[c][0] for c in err_cats if devb.get(c, [0, 0])[0]) / len(err_cats) * 100
macro_v2 = sum(v2[c][1] / v2[c][0] for c in err_cats if v2.get(c, [0, 0])[0]) / len(err_cats) * 100

# v2 per-class recall reweighted to Dev B's class counts
num = sum((v2[c][1] / v2[c][0]) * devb[c][0] for c in err_cats)
den = sum(devb[c][0] for c in err_cats)
v2_on_devb_mix = num / den * 100

# Dev B per-class recall reweighted to v2's class counts
num2 = sum((devb[c][1] / devb[c][0]) * v2[c][0] for c in err_cats)
den2 = sum(v2[c][0] for c in err_cats)
devb_on_v2_mix = num2 / den2 * 100

print()
print(f"pooled (as-run)      Dev B 52.78%   v2 56.93%   delta +4.15")
print(f"macro over 9 classes Dev B {macro_b:.2f}%   v2 {macro_v2:.2f}%   delta {macro_v2 - macro_b:+.2f}")
print(f"v2 per-class recalls applied to Dev B class mix : {v2_on_devb_mix:.2f}%")
print(f"Dev B per-class recalls applied to v2 class mix : {devb_on_v2_mix:.2f}%")
print()
print("error-class share of total error samples:")
for c in err_cats:
    share_b = devb[c][0] / sum(devb[x][0] for x in err_cats) * 100
    share_v = v2[c][0] / sum(v2[x][0] for x in err_cats) * 100
    print(f"  {c:<18} DevB {share_b:5.1f}%   v2 {share_v:5.1f}%   {share_v - share_b:+5.1f} pp")
