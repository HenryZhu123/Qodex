from copy import deepcopy
import itertools
from unittest import TestCase

from question_generation.finite_verification import solve_finite


def problem():
    return {'domains': {'x': [0,1,2], 'y': [0,1,2]},
            'constraints': [['le', 'x', 'y']],
            'queries': [{'id': 'equal', 'mode': 'count', 'predicate': ['eq','x','y']},
                        {'id': 'ordered', 'mode': 'all', 'predicate': ['le','x','y']},
                        {'id': 'reverse', 'mode': 'any', 'predicate': ['lt','y','x']}]}


class FiniteTests(TestCase):
    def test_counts_and_quantifiers(self):
        self.assertEqual(solve_finite(problem()), {'solution_count': 6,
                         'queries': {'equal': 3, 'ordered': True, 'reverse': False}})

    def test_domains_constraints_and_queries_are_validated(self):
        changes = [lambda p: p['domains'].update(x=[True]),
                   lambda p: p['domains'].update(x=[1,1]),
                   lambda p: p['domains'].update(x=[]),
                   lambda p: p.update(domains={str(i):[1] for i in range(9)}),
                   lambda p: p.update(domains={k:list(range(32)) for k in 'xyz'}),
                   lambda p: p.update(constraints=[['lt','missing',2]]),
                   lambda p: p.update(constraints=[['add','x',2]]),
                   lambda p: p.update(constraints=[['eq',True,1]]),
                   lambda p: p.update(constraints=[['eval','1+1']]),
                   lambda p: p['queries'].append(deepcopy(p['queries'][0])),
                   lambda p: p['queries'][0].update(mode='invented'),
                   lambda p: p.update(constraints=[False]),
                   lambda p: p.update(constraints=[['eq',['floordiv',1,0],1]]),
                   lambda p: p.update(constraints=[['eq',['mul',2**32,2**32],1]])]
        for mutate in changes:
            p = problem(); mutate(p)
            with self.subTest(p=p), self.assertRaises(ValueError):
                solve_finite(p)

    def test_expression_depth_limit(self):
        expr = True
        for _ in range(30):
            expr = ['not', expr]
        p = problem(); p['constraints'] = [expr]
        with self.assertRaises(ValueError):
            solve_finite(p)

    def test_signed_overflow_matches_integer_range_oracle(self):
        # All pairs of 4-bit patterns: mathematical integers with explicit wrap.
        # Same generic checker as graph ordering, without a new topic solver.
        predicate = ['or',
                     ['and',['lt','a',8],['lt','b',8],['le',8,['mod',['add','a','b'],16]]],
                     ['and',['le',8,'a'],['le',8,'b'],['lt',['mod',['add','a','b'],16],8]]]
        p = {'domains': {'a': list(range(16)), 'b': list(range(16))}, 'constraints': [True],
             'queries': [{'id':'overflow','mode':'count','predicate':predicate}]}
        expected = sum(not -8 <= (a if a<8 else a-16)+(b if b<8 else b-16) <= 7
                       for a,b in itertools.product(range(16), repeat=2))
        self.assertEqual(solve_finite(p), {'solution_count':256,'queries':{'overflow':expected}})

    def test_all_small_forward_graphs_against_permutation_oracle(self):
        edges = list(itertools.combinations('abcd',2))
        distinct = [['ne',a,b] for a,b in edges]
        for mask in range(64):
            selected = [edge for i,edge in enumerate(edges) if mask & (1<<i)]
            p = {'domains':dict.fromkeys('abcd',[0,1,2,3]),
                 'constraints':distinct+[['lt',a,b] for a,b in selected],
                 'queries':[{'id':'ab','mode':'count','predicate':['lt','a','b']}]}
            orders = [p for p in itertools.permutations('abcd')
                      if all(p.index(a)<p.index(b) for a,b in selected)]
            self.assertEqual(solve_finite(p), {'solution_count':len(orders),
                             'queries':{'ab':sum(p.index('a')<p.index('b') for p in orders)}})
