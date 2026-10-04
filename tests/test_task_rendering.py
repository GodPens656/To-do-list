import unittest
from itertools import product
from unittest.mock import Mock, patch

import flet as ft

from test_ui_state import make_front


class TaskRenderingTests(unittest.TestCase):
    def make_list(self, phone=False, count=60):
        front = make_front(phone=phone)
        front._update_control = Mock()
        data = front.back._load()
        data['tasks'] = [
            {
                'id': str(i), 'name': f'Task {i}', 'group': 'default',
                'status': False, 'created_date': '13-09-2026',
                'priority': 'Важно' if i % 2 else 'Неважно',
                'deadline': '15-09-2026' if i % 2 else '14-09-2026',
            }
            for i in range(count)
        ]
        front.back._save(data)
        front.current_status_sort = 'incomplete_first'
        return front

    @staticmethod
    def cards(front):
        return [c for c in front.tasks_cont.content.controls if isinstance(c.data, str)]

    @staticmethod
    def toggle(card):
        checkbox = next(c for c in card.content.controls if isinstance(c, ft.Checkbox))
        checkbox.value = not checkbox.value
        checkbox.on_change(Mock(control=checkbox))

    def test_group_build_reads_once_per_batch_and_does_not_save_or_publish_each_card(self):
        for count in (1, 150):
            with self.subTest(count=count):
                front = self.make_list(count=count)
                front.page.update.reset_mock()
                with patch.object(front.back, '_load', wraps=front.back._load) as reads, \
                     patch.object(front.back, '_save', wraps=front.back._save) as saves:
                    front.render_daily_repeat_tasks()
                self.assertLessEqual(reads.call_count, 5)
                saves.assert_not_called()
                front.page.update.assert_not_called()
                self.assertEqual(len(self.cards(front)), count)
                self.assertEqual(front.task_summary.value, f'Выполнено 0 из {count}  ·  Осталось {count}')

    def test_status_change_reuses_cards_and_preserves_filter_order_and_search(self):
        for phone, main_sort, status_sort in product(
            (False, True), (None, 'priority_desc', 'deadline_asc'),
            ('incomplete_first', 'complete_first'),
        ):
            with self.subTest(phone=phone, main_sort=main_sort, status_sort=status_sort):
                front = self.make_list(phone=phone, count=8)
                front.current_sort = main_sort
                front.current_status_sort = status_sort
                front.render_daily_repeat_tasks()
                original = {c.key: c for c in self.cards(front)}
                front.apply_search_filter('Task 2')
                front.page.update.reset_mock()
                with patch.object(front.utils, 'create_row_with_task', wraps=front.utils.create_row_with_task) as build, \
                     patch.object(front.back, '_save', wraps=front.back._save) as saves:
                    self.toggle(original['2'])
                build.assert_not_called()
                self.assertEqual(saves.call_count, 1)
                front.page.update.assert_called_once()
                self.assertTrue(front.back.get_task('2')['status'])
                expected = [t['id'] for t in front._sort_tasks(front.back.read_tasks())]
                self.assertEqual([c.key for c in self.cards(front)], expected)
                for card in self.cards(front):
                    self.assertIs(card, original[card.key])
                    self.assertEqual(card.visible, card.key == '2')
                self.assertEqual(original['2'].opacity, 0.6)
                self.assertEqual(front.task_summary.value, 'Найдено: 1 из 8')
                # Возврат статуса восстанавливает исходный порядок при равных ключах.
                self.toggle(original['2'])
                self.assertFalse(front.back.get_task('2')['status'])
                self.assertEqual(original['2'].opacity, 1)
                self.assertEqual([c.key for c in self.cards(front)], list(original))
                if phone:
                    self.assertIs(front.tasks_cont.content.controls[0], front.search_row_widget)

    def test_identical_names_in_different_groups_keep_their_own_task_id(self):
        front = self.make_list(count=1)
        group_id = front.back.create_group('Other')
        front.back.saveB('Task 0', group_id)
        front.current_group_id = group_id
        front.render_daily_repeat_tasks()
        card = self.cards(front)[0]
        self.toggle(card)
        self.assertFalse(front.back.get_task('0')['status'])
        self.assertTrue(front.back.get_task(card.key)['status'])

    def test_status_change_rebuilds_if_storage_has_new_tasks(self):
        front = self.make_list(count=2)
        front.render_daily_repeat_tasks()
        card = self.cards(front)[0]
        front.back.saveB('Added in background')
        self.toggle(card)
        self.assertEqual(len(self.cards(front)), 3)
        self.assertEqual(self.cards(front)[-1].key, card.key)


if __name__ == '__main__':
    unittest.main()
