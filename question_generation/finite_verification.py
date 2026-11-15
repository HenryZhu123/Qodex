"""Small bounded finite-model checker, not an interpreter for generated code.

Expressions are JSON trees. Exhaustive checking establishes claims about the
declared model only, never that the model faithfully represents a question.
"""
from __future__ import annotations

from itertools import product
import math
import operator
import re

ARITHMETIC = {"add": operator.add, "sub": operator.sub, "mul": operator.mul,
              "floordiv": operator.floordiv, "mod": operator.mod, "bitand": operator.and_}
COMPARISONS = {"eq": operator.eq, "ne": operator.ne, "lt": operator.lt, "le": operator.le}


def expression_type(expr, variables, depth=0, budget=None):
    if budget is None:
        budget = [0]
    budget[0] += 1
    if depth > 24 or budget[0] > 512:
        raise ValueError("有限模型表达式过深或过大。")
    if type(expr) is bool:
        return bool
    if type(expr) is int and abs(expr) <= 2**32:
        return int
    if isinstance(expr, str) and expr in variables:
        return int
    if not isinstance(expr, list) or not expr or not isinstance(expr[0], str):
        raise ValueError("有限模型表达式须为整数、布尔值、变量名或操作数组。")
    op, args = expr[0], expr[1:]
    types = [expression_type(a, variables, depth+1, budget) for a in args]
    if op in ARITHMETIC and types == [int, int]:
        return int
    if op in COMPARISONS and types == [int, int]:
        return bool
    if op in ("and", "or") and 2 <= len(types) <= 16 and all(t is bool for t in types):
        return bool
    if op == "not" and types == [bool]:
        return bool
    raise ValueError("有限模型操作或参数类型无效。")


def evaluate(expr, values):
    if type(expr) in (int, bool):
        return expr
    if isinstance(expr, str):
        return values[expr]
    op = expr[0]
    # Evaluate every operand: undefined arithmetic is not hidden by short-circuiting.
    args = [evaluate(a, values) for a in expr[1:]]
    if op in ARITHMETIC:
        try:
            result = ARITHMETIC[op](*args)
        except ZeroDivisionError:
            raise ValueError("有限模型存在除零状态；请修正定义域。") from None
        if abs(result) > 2**63:
            raise ValueError("有限模型中间数值越界。")
        return result
    if op in COMPARISONS:
        return COMPARISONS[op](*args)
    if op == "and":
        return all(args)
    if op == "or":
        return any(args)
    return not args[0]


def solve_finite(inputs):
    if not isinstance(inputs, dict) or inputs.keys() != {"domains", "constraints", "queries"}:
        raise ValueError("有限模型须包含domains、constraints、queries。")
    domains = inputs["domains"]
    if not isinstance(domains, dict) or not 1 <= len(domains) <= 8:
        raise ValueError("有限模型须有1至8个变量。")
    for name, domain in domains.items():
        if (not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,31}", name)
                or not isinstance(domain, list) or not 1 <= len(domain) <= 32
                or any(type(n) is not int or abs(n) > 2**32 for n in domain)
                or len(set(domain)) != len(domain)):
            raise ValueError("变量名或整数定义域无效。")
    size = math.prod(len(d) for d in domains.values())
    if size > 4096:
        raise ValueError("有限模型最多枚举4096个状态。")
    constraints, queries = inputs["constraints"], inputs["queries"]
    if not isinstance(constraints, list) or not 1 <= len(constraints) <= 16:
        raise ValueError("有限模型须有1至16个布尔约束。")
    if not isinstance(queries, list) or not 1 <= len(queries) <= 8:
        raise ValueError("有限模型须有1至8个查询。")
    budget = [0]
    for c in constraints:
        if expression_type(c, domains, budget=budget) is not bool:
            raise ValueError("约束须为布尔表达式。")
    seen = set()
    for q in queries:
        if (not isinstance(q, dict) or q.keys() != {"id", "mode", "predicate"}
                or not isinstance(q["id"], str) or not 1 <= len(q["id"]) <= 32 or q["id"] in seen
                or q["mode"] not in ("all", "any", "count")):
            raise ValueError("有限模型查询字段无效。")
        seen.add(q["id"])
        if expression_type(q["predicate"], domains, budget=budget) is not bool:
            raise ValueError("查询须为布尔表达式。")
    count = 0
    hits = dict.fromkeys(seen, 0)
    for assignment in product(*domains.values()):
        values = dict(zip(domains, assignment))
        if all(evaluate(c, values) for c in constraints):
            count += 1
            for q in queries:
                hits[q["id"]] += int(evaluate(q["predicate"], values))
    # Empty model is a failed problem, not a vacuously true proof of every option.
    if count == 0:
        raise ValueError("有限模型无满足条件的状态，不能据此证明题目答案。")
    return {"solution_count": count, "queries": {
        q["id"]: hits[q["id"]] if q["mode"] == "count" else
        (hits[q["id"]] == count if q["mode"] == "all" else hits[q["id"]] > 0) for q in queries
    }}
