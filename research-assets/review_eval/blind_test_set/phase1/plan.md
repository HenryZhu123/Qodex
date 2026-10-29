# Blind Test Set 规划方案 (Phase 1 Plan)

**方案编号**：`blind_test_v1`  
**执行技能规范**：`question-error-synthesis` (NeurIPS 2026 / COMP7608B)  
**规划生成时间**：2026-10-29 03:27:54 UTC  

---

## 一、方案目标与数据集隔离 (Data Split & Leakage Prevention)

为彻底解决 Dev Set 评测中存在的后验规则拟合（Shortcut Learning）与测试集窥探（Information Leakage）问题，正式构建独立的 **Blind Test Set（盲测集）**：
1. **源题绝对隔离**：全部新源题均从 720 道 408 真题中**完全未被 Dev Set 触碰的 397 道全新源题池**中独立抽取，确保源题哈希（Normalized Fingerprint）零重叠。
2. **重点类别全新重构 (Reconstruct from Scratch)**：
   - `type_mismatch`（题型不一致）：20 道 100% 全新构造，废除固定模板后缀，引入跨学科真实题型矛盾；
   - `option_structure`（选项结构）：20 道 100% 全新构造，引入真实排版错乱（选项丢失、非标准标号、跨行断裂等）；
   - `factual_logical`（事实/逻辑）：20 道 100% 全新构造，引入细微的定理反转、公式变量颠倒与参数矛盾。
3. **其余类别平分策略 (50% Retained / 50% New)**：
   - `typo`, `punctuation`, `missing_info`, `ambiguity`, `unsolvable`, `answer_leakage` 均由 10 道原保留样本 + 10 道全新合成样本构成。
4. **高质量干净题基线**：
   - 抽取 **60 道完全未见的干净真题** 作为正样本，严格检验误报率（FPR）。

---

## 二、样本配额与构成清单 (Quotas & Proportions)

总计规划 **240 道题目**（180 道负样本错题 + 60 道正样本干净题）：

| 类别 (Category) | 中文名称 | 规划总量 | 全新合成量 (New) | 沿用/保留量 (Retained) | 占比 | 构造与防泄露策略 |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **type_mismatch** | 题目与题型不一致 | 20 | **20** | 0 | 8.3% | **100% 全新重构**，杜绝固定机械后缀 |
| **option_structure** | 选项结构错误 | 20 | **20** | 0 | 8.3% | **100% 全新重构**，覆盖多样化真实排版破坏 |
| **factual_logical** | 事实/逻辑错误 | 20 | **20** | 0 | 8.3% | **100% 全新重构**，涉及四门学科核心定理反转 |
| **missing_info** | 信息缺失 | 20 | 10 | 10 | 8.3% | 50% 沿用 + 50% 全新删除必要解题约束 |
| **unsolvable** | 题目无解 | 20 | 10 | 10 | 8.3% | 50% 沿用 + 50% 全新构造矛盾/发散无解 |
| **typo** | 错别字 | 20 | 10 | 10 | 8.3% | 50% 沿用 + 50% 全新学科形近/音近字变异 |
| **punctuation** | 标点符号错误 | 20 | 10 | 10 | 8.3% | 50% 沿用 + 50% 全新真实标点误用 |
| **answer_leakage** | 答案泄露 | 20 | 10 | 10 | 8.3% | 50% 沿用 + 50% 全新形式泄露 |
| **ambiguity** | 语义不清 | 20 | 10 | 10 | 8.3% | 50% 沿用 + 50% 全新代词歧义与范围泛化 |
| **clean** | 干净正样本原题 | 60 | **60** | 0 | 25.0% | **100% 全新真题**，用于严格测量 FPR |
| **总计** | — | **240** | **180** | **60** | **100.0%** | **源题零复用，完全隔离** |

---

## 三、多样性约束与质检标准 (Diversity & Quality Gates)

1. **变异签名上限**：同类错误下，单一造错手法（Mutation Signature）占比**严禁超过 25%**（即每类 20 道错题必须覆盖 $\ge 5$ 种不同亚型，每种亚型不得超过 5 道）。
2. **学科均衡覆盖**：新源题分配覆盖数据结构（DS）、计算机组成原理（CO）、操作系统（OS）、计算机网络（CN）四门统考科目。
3. **单根因与精确可还原**：
   - 每道题严格只植入一处错误；
   - 必须满足 `error_text.replace(original_text, correction, 1) == clean_text`，保证标准答案能一字不差精确改回原题。
4. **定位锚点唯一性**：`anchor_text` 必须在题干中唯一可召回，杜绝位置歧义。

---

## 四、产物文件规划

- `research-assets/review_eval/blind_test_set/phase1/plan.md`（本方案人读版）
- `research-assets/review_eval/blind_test_set/phase1/plan.json`（机器可读配额）
- `research-assets/review_eval/blind_test_set/phase1/source_selection.jsonl`（240 道源题预留与指纹清单）
- `research-assets/review_eval/blind_test_set/phase1/run_state.json`（阶段审批状态控制）
