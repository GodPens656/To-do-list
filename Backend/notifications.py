import threading
import datetime
import asyncio
import sys

try:
    from plyer import notification as plyer_notification
except ImportError:
    plyer_notification = None


class NotificationService:
    """Сервис периодических уведомлений."""

    TITLE = "To-do"
    NOTIFICATION_ID = 1001
    ANDROID_PRELOAD_COUNT = 11

    def __init__(self, page, phone, settings_provider, alarm_dialog_provider=None, web=False,
                 data_provider=None):
        self.page = page
        self.phone = phone
        # web=True -> приложение открыто как сайт в браузере. Прямой доступ
        # к браузерному Notification API из Python в используемой версии
        # Flet недоступен (нет page.eval_js/run_javascript), а серверные
        # средства уведомлений (plyer/Android) для сайта не подходят —
        # plyer дёрнул бы уведомление на самом VPS, а не у посетителя.
        # Поэтому на сайте уведомления полностью отключены.
        self.web = web
        self.settings_provider = settings_provider
        self.data_provider = data_provider
        self._schedule_lock = asyncio.Lock()
        self.notifications = None
        self.permission_handler = None
        self.notification_permission = None
        self.notification_permission_requested = False
        self.stop_event = threading.Event()
        self.reload_event = threading.Event()
        self.worker = None
        self.last_scheduled_at = None
        self._android_schedule = None
        self._android_refill = None

    def setup(self):
        if self.web:
            return
        if not self.phone:
            return

        # ВАЖНО: импорт и инициализация PermissionHandler и LocalNotifications
        # разнесены по отдельным try/except. Раньше они были в одном блоке,
        # и если один из пакетов не импортировался, весь setup() прерывался
        # через return, и self.permission_handler навсегда оставался None.
        # Из-за этого кнопка "Изменить ограничение батареи" не открывала
        # системный диалог: request_battery_optimization_exemption() сразу
        # завершался, так как self.permission_handler is None.
        try:
            from flet_permission_handler import PermissionHandler
            from flet_permission_handler.types import Permission
        except ImportError:
            print("Permission handler is unavailable: package is not installed")
        else:
            self.notification_permission = Permission
            self.permission_handler = PermissionHandler()
            self.page.services.append(self.permission_handler)

        try:
            from flet_local_notifications import LocalNotifications
        except ImportError:
            print("Android local notifications are unavailable: package is not installed")
        else:
            self.notifications = LocalNotifications()
            self.page.services.append(self.notifications)

        # Сначала отправляем сервисы клиенту, затем вызываем их методы.
        self.page.update()
        # Запускаем единую последовательную цепочку инициализации Android
        self.page.run_task(self._init_android_services)

    async def _init_android_services(self):
        """Последовательная инициализация и запрос разрешений"""
        # 1. Запрашиваем обычные уведомления
        await self.request_notification_permission()

        # Даем Android небольшую паузу (0.5 сек), чтобы закрылось первое окно
        # и системный менеджер окон успел переключить контекст
        await asyncio.sleep(0.5)

        # 2. Запрашиваем оптимизацию батареи (напрямую, без условий)
        await self.request_battery_optimization_exemption()

        # 3. Планируем или очищаем расписание
        await self.refresh_android_schedule()

    async def request_battery_optimization_exemption(self):
        if self.permission_handler is None:
            return
        try:
            from flet_permission_handler.types import Permission
            print("Directly launching IGNORE_BATTERY_OPTIMIZATIONS request...")
            await self.permission_handler.request(
                Permission.IGNORE_BATTERY_OPTIMIZATIONS
            )
        except Exception as ex:
            print(f"Battery optimization exemption request failed: {ex}")

    async def request_notification_permission(self):
        if self.permission_handler is None or self.notification_permission_requested:
            return
        try:
            await self.permission_handler.request(self.notification_permission.NOTIFICATION)
            self.notification_permission_requested = True
        except Exception as ex:
            print(f"Notification permission request failed: {ex}")

    def start(self):
        if self.web:
            return
        # На мобильных устройствах логика полностью на flet_local_notifications (расписание)
        if self.phone:
            return

        if self.worker and self.worker.is_alive():
            return

        self.stop_event.clear()
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        self.reload_event.set()
        if self._android_refill is not None:
            self._android_refill.cancel()

    def reload_settings(self):
        if self.web:
            return
        if self.phone:
            self.page.run_task(self.refresh_android_schedule, True)
            return

        self.reload_event.set()

    def update_notifications(self):
        if self.web:
            return
        if self.phone:
            if not self.last_scheduled_at:
                return

            last = self.last_scheduled_at.strftime('%Y:%m:%d %H.%M.%S')
            now = datetime.datetime.now().strftime('%Y:%m:%d %H.%M.%S')

            if now > last:
                self.page.run_task(self.refresh_android_schedule)

    def data_changed(self):
        """Обновляет заранее подготовленные напоминания после изменения дел."""
        if self.web or not self.phone or self.notifications is None:
            return
        if self.settings_provider()["notifications_enabled"]:
            self.page.run_task(self.refresh_android_schedule)

    def _notification_bodies(self, settings, check_dt, data=None):
        important_enabled = settings.get("notification_important_enabled", False)
        deadline_enabled = settings.get("notification_deadline_enabled", False)
        if data is None:
            if self.data_provider is None:
                return []
            data = self.data_provider()

        bodies = []
        important_groups = set()
        deadline_groups = set()
        tomorrow = check_dt.date() + datetime.timedelta(days=1)
        for task in data.get("tasks", []):
            if task.get("status"):
                continue
            if task.get("reminder") and task.get("name"):
                name = task["name"].replace("{N}", "\n")
                bodies.append(f"Не забывайте:\n{name}")
            group_id = task.get("group", "default")
            if important_enabled and task.get("priority") == "Очень важно":
                important_groups.add(group_id)
            if deadline_enabled:
                try:
                    deadline = datetime.datetime.strptime(task.get("deadline"), "%d-%m-%Y").date()
                except (TypeError, ValueError):
                    continue
                if deadline == tomorrow:
                    deadline_groups.add(group_id)

        for group in data.get("groups", []):
            if group.get("type", "tasks") != "tasks":
                continue
            group_id = group.get("id")
            group_name = group.get("name", "")
            if group_id in important_groups:
                bodies.append(f'Есть очень важные дела в группе "{group_name}"')
            if group_id in deadline_groups:
                bodies.append(f'Скоро подойдёт дедлайн в делах группы "{group_name}"')
        return bodies

    def _parse_time(self, value, fallback):
        try:
            return datetime.datetime.strptime(value, "%H:%M").time()
        except (TypeError, ValueError):
            return fallback

    def _is_in_quiet_hours(self, check_dt, settings):
        if not settings.get("notification_quiet_enabled", False):
            return False

        start_time = self._parse_time(
            settings.get("notification_quiet_start"),
            datetime.time(22, 0),
        )
        end_time = self._parse_time(
            settings.get("notification_quiet_end"),
            datetime.time(8, 0),
        )
        current_time = check_dt.time()

        if start_time == end_time:
            return True
        if start_time < end_time:
            return start_time <= current_time < end_time
        return current_time >= start_time or current_time < end_time

    def _next_allowed_datetime(self, candidate_dt, settings):
        if not settings.get("notification_quiet_enabled", False):
            return candidate_dt

        start_time = self._parse_time(
            settings.get("notification_quiet_start"),
            datetime.time(22, 0),
        )
        end_time = self._parse_time(
            settings.get("notification_quiet_end"),
            datetime.time(8, 0),
        )

        if start_time == end_time:
            return None
        if not self._is_in_quiet_hours(candidate_dt, settings):
            return candidate_dt

        if start_time < end_time:
            return candidate_dt.replace(
                hour=end_time.hour,
                minute=end_time.minute,
                second=0,
                microsecond=0,
            )

        resume_date = candidate_dt.date()
        if candidate_dt.time() >= start_time:
            resume_date += datetime.timedelta(days=1)

        return datetime.datetime.combine(
            resume_date,
            end_time,
            tzinfo=candidate_dt.tzinfo,
        )

    async def refresh_android_schedule(self, reset_interval=False):
        if not self.phone or self.notifications is None:
            return
        # Изменения настроек и дел могут прийти во время планирования.
        async with self._schedule_lock:
            await self._refresh_android_schedule(reset_interval)

    async def _refresh_android_schedule(self, reset_interval):
        settings = self.settings_provider()
        now = datetime.datetime.now()
        interval = datetime.timedelta(minutes=settings["notification_interval"])
        pending = {when: bodies for when, bodies in (self._android_schedule or {}).items()
                   if when > now}
        schedule = {}
        if settings["notifications_enabled"]:
            # Cloud refreshes and task edits must not restart the interval.
            next_time = now + interval if reset_interval else next(iter(pending), now + interval)
            data = self.data_provider() if self.data_provider is not None else {}
            for _ in range(self.ANDROID_PRELOAD_COUNT):
                next_time = self._next_allowed_datetime(next_time, settings)
                if next_time is None:
                    break
                schedule[next_time] = self._notification_bodies(settings, next_time, data)
                next_time += interval

        if self._android_schedule is None or schedule != pending:
            # The first refresh also clears alarms left by an older app version.
            try:
                await self.notifications.cancel_all_notifications()
                notification_id = 100000
                for when, bodies in schedule.items():
                    for body in bodies:
                        delay = max(1, int((when - datetime.datetime.now()).total_seconds()))
                        await self._schedule_android_notification(
                            notification_id, delay, self.TITLE, body,
                        )
                        notification_id += 1
            except Exception as ex:
                print(f"Android notification schedule failed: {ex}")
                self._android_schedule = None
                self._refill_android_after(30)
                return
        self._android_schedule = schedule
        self.last_scheduled_at = next(reversed(schedule), None)
        if self.last_scheduled_at is not None:
            # Refill before the last preloaded alarm, even on an idle screen.
            refill_at = max(next(iter(schedule)), self.last_scheduled_at - interval / 2)
            self._refill_android_after((refill_at - datetime.datetime.now()).total_seconds())
        elif self._android_refill is not None:
            self._android_refill.cancel()

    def _refill_android_after(self, seconds):
        if self._android_refill is not None:
            self._android_refill.cancel()
        if not self.stop_event.is_set():
            self._android_refill = asyncio.get_running_loop().call_later(
                max(1, seconds), self.page.run_task, self.refresh_android_schedule,
            )

    def _run(self):
        while not self.stop_event.is_set():
            settings = self.settings_provider()
            if not settings["notifications_enabled"]:
                self._wait_seconds(5)
                continue

            interval_seconds = settings["notification_interval"] * 60
            was_reloaded = self._wait_seconds(interval_seconds)
            if was_reloaded or self.stop_event.is_set():
                continue

            current_settings = self.settings_provider()
            if current_settings["notifications_enabled"] and not self._is_in_quiet_hours(
                datetime.datetime.now(),
                current_settings,
            ):
                self.notify()

    def _wait_seconds(self, seconds):
        self.reload_event.clear()
        was_reloaded = self.reload_event.wait(seconds)
        self.reload_event.clear()
        return was_reloaded

    def notify(self):
        if self.web:
            return
        if self.phone:
            if self.notifications is None:
                return
            self.page.run_task(self.refresh_android_schedule)
        else:
            threading.Thread(
                target=self._notify_desktop,
                daemon=True,
            ).start()

    def _notify_desktop(self):
        settings = self.settings_provider()
        now = datetime.datetime.now()
        if not settings["notifications_enabled"] or self._is_in_quiet_hours(now, settings):
            return
        for body in self._notification_bodies(settings, now):
            self.show_desktop_notification(self.TITLE, body)

    async def _schedule_android_notification(
            self,
            notification_id,
            delay_seconds,
            title,
            body,
    ):
        if not self.notification_permission_requested:
            await self.request_notification_permission()

        await self.notifications.schedule_notification(
            id=notification_id,
            title=title,
            body=body,
            delay_seconds=delay_seconds,
        )

    def show_desktop_notification(self, title, body):
        if plyer_notification is None:
            print("Desktop notifications are unavailable: plyer is not installed")
            return

        try:
            # Plyer's Windows balloon has room for 255 UTF-16 code units.
            if sys.platform == "win32":
                encoded = body.encode("utf-16-le")
                if len(encoded) > 510:
                    body = encoded[:508].decode("utf-16-le", errors="ignore") + "…"
            plyer_notification.notify(
                title=title,
                message=body,
                app_name=self.TITLE,
                timeout=10,
            )
        except Exception as ex:
            print(f"Desktop notification failed: {ex}")
