from random import Random
from unittest import TestCase

from question_generation.paging import (
    Choice,
    PagingInstance,
    build_choices,
    check_choices,
    create_instance,
    render_stem,
)


class PagingTests(TestCase):
    def test_hand_calculated_instance(self):
        instance = PagingInstance(256, 0x02B4, {1: 4, 2: 5, 3: 7})
        choices, answer_id = build_choices(instance, Random(42))
        self.assertEqual(choices[answer_id].address, 0x05B4)
        self.assertEqual(
            {choice.address for choice in choices.values()},
            {0x02B4, 0x0500, 0x05B4, 0x07B4},
        )
        self.assertIsNone(check_choices(instance, choices, answer_id))
        self.assertIn("虚页 2 对应物理页框 5", render_stem(instance))
        self.assertIn("0x2B4", render_stem(instance))

    def test_zero_offset_replaces_the_colliding_distractor(self):
        instance = PagingInstance(256, 0x0200, {1: 4, 2: 5, 3: 7})
        choices, answer_id = build_choices(instance, Random(42))
        self.assertEqual(choices[answer_id].address, 0x0500)
        self.assertEqual(
            {choice.address for choice in choices.values()},
            {0x0200, 0x0400, 0x0500, 0x0700},
        )
        self.assertTrue(any("误减 1" in choice.explanation for choice in choices.values()))
        self.assertIsNone(check_choices(instance, choices, answer_id))

    def test_seed_and_answer_id_survive_reordering(self):
        def generate():
            rng = Random(42)
            instance = create_instance(rng, 4096, None)
            return instance, *build_choices(instance, rng)

        instance, choices, answer_id = generate()
        self.assertEqual(generate(), (instance, choices, answer_id))
        reordered = dict(reversed(tuple(choices.items())))
        self.assertIsNone(check_choices(instance, reordered, answer_id))

    def test_self_check_rejects_bad_answer_ids_and_duplicate_addresses(self):
        instance = PagingInstance(256, 0x02B4, {1: 4, 2: 5, 3: 7})
        choices, answer_id = build_choices(instance, Random(42))
        wrong_id = next(key for key in choices if key != answer_id)
        for bad_id in ("missing", wrong_id):
            with self.subTest(bad_id=bad_id):
                self.assertIsNotNone(check_choices(instance, choices, bad_id))
        choices[wrong_id] = Choice(choices[answer_id].address, "重复地址。")
        self.assertIsNotNone(check_choices(instance, choices, answer_id))
