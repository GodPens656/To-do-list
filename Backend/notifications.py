import threading
import datetime
import asyncio

try:
    from plyer import notification as plyer_notification
except ImportError:
    plyer_notification = None


class NotificationService:
    """Сервис периодических уведомлений."""

    TITLE = "To-do"
    BODY = "Не забывайте о своих делах"
    NOTIFICATION_ID = 1001
    ANDROID_PRELOAD_COUNT = 11

    def __init__(self, page, phone, settings_provider, alarm_dialog_provider=None, web=False):
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
        self.notifications = None
        self.permission_handler = None
        self.notification_permission = None
        self.notification_permission_requested = False
        self.stop_event = threading.Event()
        self.reload_event = threading.Event()
        self.worker = None
        self.last_scheduled_at = None

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

    # ТЕПЕРЬ ОТСТУП ПРАВИЛЬНЫЙ (ровно 4 пробела от края класса):
    async def request_notification_permission(self):
        try:
            await self.permission_handler.request(self.notification_permission.NOTIFICATION)
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

    def reload_settings(self):
        if self.web:
            return
        if self.phone:
            self.page.run_task(self.refresh_android_schedule)
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
            return candidate_dt + datetime.timedelta(days=3650)
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

    async def refresh_android_schedule(self):
        if not self.phone or self.notifications is None:
            return

        # ИСПРАВЛЕНИЕ: Сначала ВСЕГДА отменяем все старые уведомления
        try:
            await self.notifications.cancel_all_notifications()
            print("All previously scheduled Android notifications canceled.")
        except Exception as ex:
            print(f"Cancel all failed: {ex}")

        # Теперь проверяем настройки
        settings = self.settings_provider()
        if not settings["notifications_enabled"]:
            self.last_scheduled_at = None
            print("Notifications are disabled. Schedule cleared.")
            return

        interval = settings["notification_interval"]
        schedule_count = self.ANDROID_PRELOAD_COUNT

        print(f"Scheduling {schedule_count} new notifications with interval {interval} min...")
        now = datetime.datetime.now()
        next_time = now + datetime.timedelta(minutes=interval)

        for index in range(schedule_count):
            next_time = self._next_allowed_datetime(next_time, settings)
            delay_seconds = max(1, int((next_time - now).total_seconds()))
            notification_id = 100000 + index
            await self._schedule_android_notification(
                notification_id, delay_seconds, self.TITLE, self.BODY,
            )
            next_time += datetime.timedelta(minutes=interval)

        self.last_scheduled_at = next_time - datetime.timedelta(minutes=interval)
        print(f"Last notification scheduled at: {self.last_scheduled_at}")

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
                target=self.show_desktop_notification,
                args=(self.TITLE, self.BODY),
                daemon=True,
            ).start()

    async def _schedule_android_notification(
            self,
            notification_id,
            delay_seconds,
            title,
            body,
    ):
        if not self.notification_permission_requested:
            await self.request_notification_permission()

        try:
            await self.notifications.schedule_notification(
                id=notification_id,
                title=title,
                body=body,
                delay_seconds=delay_seconds,
            )
        except Exception as ex:
            print(f"Local scheduled notification failed: {ex}")

    def show_desktop_notification(self, title, body):
        if plyer_notification is None:
            print("Desktop notifications are unavailable: plyer is not installed")
            return

        try:
            plyer_notification.notify(
                title=title,
                message=body,
                app_name=self.TITLE,
                timeout=10,
            )
        except Exception as ex:
            print(f"Desktop notification failed: {ex}")
