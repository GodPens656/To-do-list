"""Isolated loading games: no real account, filesystem saves or network."""

import asyncio
import copy
import threading
import time
import unittest
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

import flet as ft

from Frontend.loading import LoadingScreen
from Frontend.theme import THEME_STYLES, THEME_EFFECTS, get_theme_colors
from test_ui_state import make_front


class LoadingGameTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.games = []
        self.workers = []

    async def asyncTearDown(self):
        for game in self.games:
            game.stop()
        await asyncio.gather(*self.workers, return_exceptions=True)
        # Includes the Event.wait tasks created by wait_for().
        self.assertEqual(asyncio.all_tasks(), {asyncio.current_task()})

    def game(self):
        libs = SimpleNamespace(
            colors=get_theme_colors("chatgpt-light"), text_size=lambda size: size,
            host=lambda **kwargs: ft.Container(**kwargs),
        )
        game = LoadingScreen(libs)
        game._game.update = Mock()
        self.games.append(game)
        return game

    async def start(self, game, *, delay=0):
        game.REVEAL_DELAY = delay
        game._worker = asyncio.create_task(game._run())
        self.workers.append(game._worker)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    async def test_real_two_second_threshold_and_fast_close(self):
        fast, slow = self.game(), self.game()
        self.assertEqual(slow.REVEAL_DELAY, 2.0)
        await self.start(fast, delay=fast.REVEAL_DELAY)
        await self.start(slow, delay=slow.REVEAL_DELAY)
        await asyncio.sleep(0.02)
        self.assertFalse(fast._game.visible)
        self.assertFalse(slow._game.visible)
        fast.stop()
        await asyncio.sleep(2.02)
        self.assertFalse(fast._game.visible)
        fast._game.update.assert_not_called()
        self.assertTrue(slow._game.visible)
        self.assertEqual(len(slow._cards), 3)

    async def test_whole_card_and_accessibility_taps_score_only_once(self):
        game = self.game()
        await self.start(game)
        cards = list(game._cards.values())
        await asyncio.gather(
            cards[0].control.on_click(None), cards[0].control.on_click(None),
            cards[0].checkbox.on_change(None), cards[1].control.on_click(None),
        )
        self.assertEqual(game.score, 2)
        self.assertEqual(game._score_text.value, "Поймано: 2")
        self.assertTrue(cards[0].checkbox.value)
        self.assertLess(cards[0].control.opacity, 1)
        self.assertLess(cards[0].control.scale, 1)
        await asyncio.sleep(game.FADE_SECONDS + 0.05)
        self.assertNotIn(cards[0], list(game._cards.values()))
        self.assertEqual(len(game._cards), 3)
        await cards[0].control.on_click(None)
        self.assertEqual(game.score, 2)

    async def test_unpressed_cards_expire_without_penalty_or_overlap(self):
        game = self.game()
        await self.start(game)
        old = list(game._cards.values())
        for card in old:
            card.expires = monotonic() + 0.01
        game._wake.set()
        await asyncio.sleep(0.04)
        self.assertEqual(game.score, 0)
        self.assertEqual(len(game._cards), 3)
        self.assertFalse(any(card is previous for card in game._cards.values() for previous in old))
        # Repeated replacements always keep one card per cell, with 54px touch
        # targets, and leave the other three cells free.
        positions = set(game._cards)
        for i in range(50):
            game._replace_expired(monotonic() + 10 * (i + 1))
            self.assertEqual(len(game._cards), 3)
            self.assertEqual(sum(slot.content is not None for slot in game._slots), 3)
            self.assertTrue(all(c.control.height >= 48 for c in game._cards.values()))
            positions.update(game._cards)
        self.assertGreater(len(positions), 3)

    async def test_unmount_during_fade_stops_updates_and_queued_clicks(self):
        game = self.game()
        await self.start(game)
        card = next(iter(game._cards.values()))
        await card.control.on_click(None)
        game.will_unmount()
        calls = game._game.update.call_count
        await asyncio.sleep(game.FADE_SECONDS + 0.03)
        await next(c for c in game._cards.values() if not c.caught).control.on_click(None)
        self.assertEqual(game.score, 1)
        self.assertEqual(game._game.update.call_count, calls)
        self.assertTrue(self.workers[-1].done())

    async def test_detached_control_stops_worker_without_page_update(self):
        game = self.game()
        game._game.update.side_effect = RuntimeError("not attached")
        await self.start(game)
        self.assertTrue(game._stopped)
        await asyncio.sleep(0)
        self.assertTrue(self.workers[-1].done())

    async def test_mount_is_idempotent_and_stopped_screen_never_restarts(self):
        game = self.game()
        page = Mock()
        page.run_task.side_effect = lambda fn: asyncio.create_task(fn())
        with patch.object(LoadingScreen, "page", new_callable=PropertyMock, return_value=page):
            game.did_mount()
            self.workers.append(game._worker)
            game.did_mount()
            game.will_unmount()
            game.did_mount()
        page.run_task.assert_called_once()


class LoadingNavigationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.front = make_front()
        self.front.show_groups()
        self.games = []
        self.workers = []
        self.jobs = []
        self.front.page.run_task.side_effect = lambda fn, *args: self.jobs.append((fn, args))

    async def asyncTearDown(self):
        self.front._stop_loading_game()
        for game in self.games:
            game.stop()
        await asyncio.gather(*self.workers, return_exceptions=True)
        await asyncio.sleep(0)
        self.assertEqual(asyncio.all_tasks(), {asyncio.current_task()})

    async def mount(self, game, *, delay=0):
        game._game.update = Mock()
        game.REVEAL_DELAY = delay
        game._worker = asyncio.create_task(game._run())
        self.games.append(game)
        self.workers.append(game._worker)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    def update_job(self):
        fn, args = self.jobs[-1]
        return fn(*args)

    async def test_back_and_reopening_reset_score_and_ignore_old_completion(self):
        first = self.front._open_loading_view()
        await self.mount(first)
        await next(iter(first._cards.values())).control.on_click(None)
        self.front._on_view_pop()
        self.assertTrue(first._stopped)
        self.assertIs(self.front.screen_stack[-1], self.front.main_cont)
        second = self.front._open_loading_view()
        await self.mount(second)
        self.front._close_loading_view(first)
        self.assertIs(self.front.screen_stack[-1], second)
        self.assertFalse(second._stopped)
        self.assertEqual(second.score, 0)
        self.front._close_loading_view(second)
        self.assertTrue(second._stopped)

    async def test_native_back_and_old_route_do_not_close_new_game(self):
        front = self.front
        front.web = False
        front.page.views = [ft.View(route="/base", controls=[ft.Container()])]
        front.page.push_route = AsyncMock()
        first = front._open_loading_view()
        old = front._loading_widget
        await self.mount(old)
        front._on_view_pop()
        second = front._open_loading_view()
        new = front._loading_widget
        await self.mount(new)
        self.assertNotEqual(first, second)
        front._close_loading_view(first)
        self.assertEqual(front.page.views[-1].route, second)
        self.assertFalse(new._stopped)
        front._close_loading_view(second)
        self.assertEqual(front.page.views[-1].route, "/base")
        self.assertTrue(old._stopped)
        self.assertTrue(new._stopped)

    async def test_update_finishes_during_game_without_waiting_for_animation(self):
        front = self.front
        before = copy.deepcopy(front.web_store._data)
        front.update_tasks()
        game = front._loading_widget
        await self.mount(game)
        await next(iter(game._cards.values())).control.on_click(None)
        with patch.object(front, "_refresh_task_data"):
            await self.update_job()
        self.assertTrue(game._stopped)
        self.assertIs(front.screen_stack[-1], front.main_cont)
        self.assertEqual(front.web_store._data, before)

    async def assert_game_responds(self, game):
        card = next(iter(game._cards.values()))
        score = game.score
        await card.control.on_click(None)
        self.assertEqual(game.score, score + 1)
        self.assertEqual(game._score_text.value, f"Поймано: {score + 1}")
        await asyncio.sleep(0.08)
        self.assertNotIn(card, list(game._cards.values()))

    async def test_storage_preparation_keeps_loading_game_responsive(self):
        front = self.front
        for owner, method in ((front, "check_and_add_repeat_task"), (front.back, "read_tasks")):
            with self.subTest(method=method):
                started, release = threading.Event(), threading.Event()
                original = getattr(owner, method)

                def slow_storage():
                    started.set()
                    if not release.wait(2):
                        raise TimeoutError("Storage preparation blocked the page loop")
                    return original()

                with patch.object(owner, method, side_effect=slow_storage):
                    front.update_tasks()
                    game = front._loading_widget
                    game.FADE_SECONDS = 0.01
                    await self.mount(game)
                    job = asyncio.create_task(self.update_job())
                    try:
                        for _ in range(100):
                            if started.is_set() or job.done():
                                break
                            await asyncio.sleep(0.005)
                        self.assertTrue(started.is_set())
                        self.assertFalse(job.done())
                        await self.assert_game_responds(game)
                        self.assertFalse(job.done())
                    finally:
                        release.set()
                        await job
                self.assertTrue(game._stopped)

    async def test_building_tasks_and_notes_keeps_game_and_wallpaper_running(self):
        for web in (True, False):
            for notes in (False, True):
                with self.subTest(web=web, notes=notes):
                    front = self.front
                    front.web = web
                    front.page.push_route = AsyncMock()
                    front.web_store._persist = Mock()
                    data = front.back._load()
                    data["tasks"] = []
                    group = data["groups"][0]
                    group.update(type="notes" if notes else "tasks", notes=[])
                    records = [dict(id=str(i), group="default", name=f"Task {i}",
                                    text=f"Note {i}", status=i % 2 == 0,
                                    created_date="01-11-2026") for i in range(80)]
                    if notes:
                        group["notes"] = records
                    else:
                        data["tasks"] = records
                    front.back.store.save_all_sections(data)
                    front.current_group_id = "default"
                    front.current_status_sort = "complete_first"
                    front.current_search = front.search_field.value = "1"
                    front.wallpaper.configure("waves", 60, "#6750A4", False)
                    built_on = []
                    build = front.utils.create_row_with_task

                    def slow_card(*args, **kwargs):
                        built_on.append(threading.get_ident())
                        time.sleep(0.003)  # Simulate expensive control construction.
                        return build(*args, **kwargs)

                    with patch.object(front.utils, "create_row_with_task", side_effect=slow_card):
                        front.update_tasks(front.show_groups)
                        game = front._loading_widget
                        game.FADE_SECONDS = 0.01
                        await self.mount(game)
                        canvas = front.page.views[-1]._nd_wallpaper_layer.canvas
                        canvas.resize_to(360, 800)
                        canvas.update = Mock()
                        front.wallpaper._mounted.add(canvas)
                        wallpaper = asyncio.create_task(
                            front.wallpaper._animate(front.wallpaper._generation))
                        front.wallpaper._task = wallpaper
                        self.workers.append(wallpaper)
                        job = asyncio.create_task(self.update_job())
                        try:
                            while not built_on and not job.done():
                                await asyncio.sleep(0.001)
                            self.assertFalse(job.done())
                            frames = canvas.update.call_count
                            await self.assert_game_responds(game)
                            self.assertFalse(job.done())
                            self.assertGreater(canvas.update.call_count, frames)
                            await job
                        finally:
                            front.wallpaper.stop()
                            await job
                    cards = [c for c in front.tasks_cont.content.controls
                             if isinstance(c.data, str)]
                    self.assertEqual(len(built_on), len(records))
                    self.assertEqual(set(built_on), {threading.get_ident()})
                    self.assertEqual([c.key for c in cards], [r["id"] for r in records])
                    self.assertEqual([c.visible for c in cards], ["1" in r["id"] for r in records])
                    self.assertTrue(game._stopped)

    async def test_navigation_during_build_does_not_append_stale_cards(self):
        front = self.front
        front.UI_BUILD_BUDGET = 0
        front.web_store._persist = Mock()
        data = front.back._load()
        data["tasks"] = [dict(id=str(i), name=f"Task {i}", group="default") for i in range(80)]
        front.back.store.save_all_sections(data)
        other = front.back.create_group("Other")
        other_task = front.back.saveB("Other task", other)
        callback = Mock()
        front.update_tasks(callback)
        game = front._loading_widget
        await self.mount(game)
        job = asyncio.create_task(self.update_job())
        try:
            while not any(c.key == "0" for c in front.tasks_cont.content.controls) and not job.done():
                await asyncio.sleep(0)
            self.assertFalse(job.done())
            front.current_group_id = other
            front.show_groups()
            await job
            cards = [c for c in front.tasks_cont.content.controls if isinstance(c.data, str)]
            self.assertEqual([c.key for c in cards], [other_task])
            callback.assert_not_called()
        finally:
            await job

    async def test_fast_update_and_callback_paths_always_dispose_game(self):
        for callback in (None, self.front.show_groups, lambda: None):
            self.front.update_tasks(callback)
            game = self.front._loading_widget
            await self.mount(game, delay=2)
            with patch.object(self.front, "_refresh_task_data"):
                await self.update_job()
            self.assertFalse(game._game.visible)
            self.assertTrue(game._stopped)
            self.assertIs(self.front.screen_stack[-1], self.front.main_cont)

    async def test_update_and_callback_errors_close_loading(self):
        def failed_callback():
            raise RuntimeError("private callback error")

        for callback, error in ((None, RuntimeError("private network error")),
                                (failed_callback, None)):
            self.front.update_tasks(callback)
            game = self.front._loading_widget
            await self.mount(game)
            with patch.object(self.front, "_refresh_task_data", side_effect=error), \
                    patch.object(self.front.libs, "open_dialog") as dialog:
                await self.update_job()
            self.assertTrue(game._stopped)
            self.assertIs(self.front.screen_stack[-1], self.front.main_cont)
            self.assertNotIn("private", dialog.call_args.args[1])

    async def test_cancelled_update_closes_game(self):
        self.front.update_tasks()
        game = self.front._loading_widget
        await self.mount(game)
        with patch.object(self.front, "_refresh_task_data", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await self.update_job()
        self.assertTrue(game._stopped)
        self.assertIs(self.front.screen_stack[-1], self.front.main_cont)

    async def test_startup_error_returns_to_tasks_without_a_previous_screen(self):
        front = self.front
        for web in (True, False):
            front.web = web
            front.screen_stack.clear()
            front.wallpaper.clear_view(front.root_view)
            front.root_view.controls.clear()
            front.page.views = [front.root_view]
            front.page.push_route = AsyncMock()
            front.update_tasks()
            game = front._loading_widget
            await self.mount(game)
            with patch.object(front, "_refresh_task_data", side_effect=RuntimeError("offline")), \
                    patch.object(front.libs, "open_dialog"):
                await self.update_job()
            self.assertTrue(game._stopped)
            if web:
                self.assertIs(front.screen_stack[-1], front.main_cont)
            else:
                self.assertEqual(front.page.views[-1].route, "/groups")

    async def test_callback_can_push_a_screen_without_leaving_loading_in_history(self):
        front = self.front
        for web in (True, False):
            front.web = web
            front.page.push_route = AsyncMock()
            front.page.views = [front.root_view]
            front.update_tasks(front.open_settings)
            game = front._loading_widget
            token = front._loading_token
            await self.mount(game)
            with patch.object(front, "_refresh_task_data"):
                await self.update_job()
            self.assertTrue(game._stopped)
            if web:
                self.assertTrue(all(screen is not game for screen in front.screen_stack))
                self.assertIsNot(front.screen_stack[-1], front.main_cont)
                front.close_page()
            else:
                self.assertTrue(all(view.route != token for view in front.page.views))

    async def test_login_and_register_errors_and_failed_results_stop_game(self):
        front = self.front
        for action, method, result in (
            ("login", "alg_for_login", {"Connect": False, "Have account": False}),
            ("register", "alg_for_regist", {"Connect": False, "Already have account": False}),
        ):
            for error in (None, RuntimeError("private network error")):
                getattr(front, action)("demo", "demo")
                game = front._loading_widget
                await self.mount(game)
                with patch("Frontend.init_page.asyncio.to_thread", new_callable=AsyncMock,
                           return_value=result, side_effect=error), patch.object(front.libs, "open_dialog"):
                    await self.update_job()
                self.assertTrue(game._stopped)
                self.assertIs(front.screen_stack[-1], front.main_cont)

    async def test_navigation_close_and_disconnect_stop_before_reveal(self):
        for leave in (self.front.show_groups, self.front.open_settings,
                      self.front.page.on_disconnect, self.front.page.on_close,
                      self.front._reset_root_view):
            game = self.front._open_loading_view()
            await self.mount(game, delay=2)
            leave()
            self.assertTrue(game._stopped)
            self.assertFalse(game._game.visible)

    async def test_disabled_loading_setting_does_not_construct_or_schedule_game(self):
        front = self.front
        settings = dict(front.back2.read_settings(), load_screen=False)
        front.back2.read_settings = Mock(return_value=settings)
        with patch.object(front.main_widgets, "build_loading_widget") as build:
            front.update_tasks()
        build.assert_not_called()
        self.assertEqual(self.jobs, [])
        front.cloud.alg_for_start_app.assert_called_once()

    async def test_all_existing_palettes_and_effects_build_the_game(self):
        for theme in THEME_STYLES:
            for dark in (False, True):
                for effect in THEME_EFFECTS:
                    with self.subTest(theme=theme, dark=dark, effect=effect):
                        front = make_front(theme=theme, dark=dark, effect=effect, phone=True)
                        game = front.main_widgets.build_loading_widget()
                        game._replace_expired(monotonic())
                        front.libs.prepare(game)
                        self.assertEqual(game._score_text.color, front.colors["TxtColor"])
                        self.assertTrue(all(card.checkbox.active_color == front.colors["ProgressColor"]
                                            for card in game._cards.values()))
                        self.assertFalse(game._game.visible)
                        self.assertEqual(game.score, 0)


if __name__ == "__main__":
    unittest.main()
