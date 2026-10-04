import threading


class AutoUpdateService:
    """Фоновый сервис автоматического обновления дел из облака.

    Раз в заданный интервал (по умолчанию 10 минут) в отдельном потоке
    записывает дату и время обновления в
    saves/user_data/last_update_tasks.txt и, если передан колбэк
    on_refresh, просит интерфейс выполнить обычное обновление —
    такое же, как при нажатии кнопки "Обновить" (экран загрузки и
    переход на экран групп). Саму синхронизацию с облаком выполняет
    вызванный колбэк (тот же код, что и у ручного обновления), поэтому
    здесь она не дублируется.
    """


    DEFAULT_INTERVAL_MINUTES = 10

    def __init__(self, page, back2, on_refresh=None, interval_minutes=DEFAULT_INTERVAL_MINUTES):
        self.page = page
        self.back2 = back2
        self.on_refresh = on_refresh
        self.interval_seconds = interval_minutes * 60
        self.stop_event = threading.Event()
        self.worker = None

    def start(self):
        """Запускает фоновый поток автообновления (если он ещё не запущен)."""
        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def stop(self):
        """Останавливает фоновый поток автообновления."""
        self.stop_event.set()

    def _run(self):
        # stop_event.wait(...) возвращает True, если событие установили
        # (значит, нужно остановиться), и False по истечении таймаута
        # (значит, пришло время очередного обновления).
        while not self.stop_event.wait(self.interval_seconds):
            self._update_once()

    def _update_once(self):
        try:
            self.back2.write_last_update_tasks()
        except Exception as ex:
            print(f"Автообновление: не удалось записать время обновления: {ex}")

        if self.on_refresh is not None:
            try:
                # page.run_task безопасно передаёт выполнение корутины
                # в event loop страницы, из которого можно менять UI.
                # Сама синхронизация с облаком и вся отрисовка выполняются
                # внутри колбэка (update_and_show_groups), тем же кодом,
                # что и при нажатии кнопки "Обновить".
                self.page.run_task(self.on_refresh)
            except Exception as ex:
                print(f"Автообновление: не удалось обновить интерфейс: {ex}")
