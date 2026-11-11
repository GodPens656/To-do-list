Этап 2 выполнен: ленивые меню карточек и точечные обновления UI.

TaskActionsMenu содержит обычную кнопку с прежним многоточием и создаёт PopupMenuItem, Icon и TextStyle перед первым открытием. Сохранены порядок, подписи, иконки, tooltip и обработчики редактирования, копирования, повторения и удаления. Пункты переиспользуются. Возвращаемая структура create_row_with_task осталась из пяти элементов; delete/edit — лёгкие цели с on_click и tooltip. Привязки Front и NotesMixin сохранены.

Оформление меню берётся из прежнего PopupMenuButton, подготовленного существующими стилями: те же цвет, форма, тень, высота и цвета иконок. Якорь наследует штатную тему IconButton и не получает дополнительную стеклянную оболочку. Обе реализации Flet 0.82 используют общий buildPopupMenuEntries: https://github.com/flet-dev/flet/blob/v0.82.0/packages/flet/lib/src/utils/popup_menu.dart

Чекбокс без сортировки статусов обновляет только карточку и сводку. Кнопка undo обновляется своим callback; её стеклянное оформление также подготавливается отдельно. При сортировке статусов сохранено обновление основного списка, поскольку карточка может переместиться либо фоновая синхронизация могла изменить его состав.

Заменены 37 мест с полным page.update() на обновление контролов или небольшого поддерева. Полные обновления темы, навигации, сервисов, открытия диалогов и регистрации DatePicker/локали сохранены. Количество вызовов без аргументов в init_page.py: 48 → 24; в settings.py: 11 → 1 (оставшийся вызов — резервный путь для ещё не смонтированных контролов).

Ниже медианы пяти повторов для 1000 дел. Патч чекбокса измерен без сортировки статусов; это Python/Flet и упаковка msgpack, не сеть, GPU или полный физический отклик устройства.

| Оформление | Раскладка | Сборка карточек, мс: до → после | Патч чекбокса, мс: до → после | Начальный пакет, байт: до → после |
|---|---|---:|---:|---:|
| none | desktop | 735.897 → 611.168 | 1584.257 → 1.483 | 2785522 → 2146522 |
| none | phone | 684.744 → 535.542 | 1508.111 → 1.449 | 2658115 → 2019115 |
| liquid_glass_half | desktop | 1025.179 → 625.050 | 1868.902 → 1.741 | 3465167 → 2826167 |
| liquid_glass_half | phone | 777.261 → 532.432 | 1757.853 → 1.619 | 3286961 → 2647961 |
| liquid_glass | desktop | 945.387 → 706.544 | 1766.085 → 1.734 | 3297217 → 2658217 |
| liquid_glass | phone | 781.977 → 532.159 | 1756.685 → 1.825 | 3286961 → 2647961 |

Все 18 профилей (50/300/1000 дел, desktop/phone, три оформления): [bench_ui_before.txt](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/bench_ui_before.txt>) и [bench_ui_after.txt](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/bench_ui_after.txt>). В каждом профиле удалены 7 начальных контролов на карточку; 4000 пунктов меню на 1000 дел заменены нулём до открытия. Оба замера выполнены одним [bench_ui.py](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/bench_ui.py>); для «до» загружался снимок Frontend перед этапом 2, для «после» — текущий код. Данные синтетические, облако отключено. Время обработчика чекбокса с web-store записано отдельно и не смешивается со временем патча.

Проверки: 21 новый UI-тест прошёл; полный прогон — 579 passed, 11 failed, 1810 subtests passed. Набор 11 падений совпал с этапом 1. Журнал: [artifacts/stage2/pytest_stage2.txt](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/pytest_stage2.txt>). Тесты: [tests/test_lazy_task_actions.py](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/tests/test_lazy_task_actions.py>). compileall Frontend Backend и проверка пробелов в diff прошли.

В существующих тестах обновлён поиск ленивого меню. В трёх тестах несмонтированных форм добавлена имитация _update_control: они используют Mock страницы или подменяют открытие формы. Проверки бизнес-логики не ослаблены; отдельные новые тесты проверяют реальные патчи ObjectPatch, отсутствие обхода других карточек, состояние undo и повторное открытие DatePicker.

UI_BUILD_BUDGET, асинхронная сборка и подпись рендера сохранены. Файлы controls.py (SurfaceHost.is_isolated, LazyListView, _StableButtonStyle), glass.py, libs.py, notes.py и reordering.py не менялись. Кэш Backend этапа 1 и обои не изменялись.

Порционная загрузка не внедрена по разрешённому в задании варианту. apply_search_filter и _refresh_task_overview читают уже созданные карточки, а LongPressReorder._record_reorder_items формирует порядок по видимым контролам. _task_render_structure и повторный рендер сверяют структуру полного списка. Ограничение первыми 40 карточками без переработки поиска, счётчиков, разделителей дат и сопоставления порядка скрытых записей изменило бы поведение. LazyListView и существующие кооперативные порции сборки сохранены.

Остаточные ограничения: полная сборка и структурные перестановки больших списков остаются пропорциональны их размеру. Первое открытие меню требует обмена с Python, последующие используют созданные пункты. Полный отклик Flutter, реальный Android и скорость сети не измерялись.

Живая визуальная проверка не завершена: computer-use сообщил, что доступ к Firefox не разрешён; отдельный встроенный браузер получил ERR_EMPTY_RESPONSE для локального тестового стенда. Стенд остановлен. Внешние данные и пользовательские приложения не изменялись.

Вручную: открыть меню первым кликом в обычном и обоих стеклянных оформлениях на ПК/телефоне; проверить положение, размеры и все действия у дела и заметки, в том числе после редактирования. Проверить чекбокс и undo, поиск, сортировку статусов, перетаскивание, даты и повторное открытие DatePicker, импорт/экспорт, шифрование и бэкапы. Отдельно проверить web-режим.

Обоснования точечных замен для описания коммита: исходная строка, новый вызов и причина (те же комментарии стоят в коде).

| Файл и исходная строка | Новый вызов | Причина |
|---|---|---|
| [Frontend/init_page.py:273](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:273>) | `self._update_control(card)` | Состояние проверки пароля меняется только внутри карточки входа. |
| [Frontend/init_page.py:292](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:292>) | `self._update_control(card)` | Ошибка и доступность полей относятся к той же карточке. |
| [Frontend/init_page.py:1220](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:1220>) | `self._update_control(deadline_field)` | Выбор даты меняет только значение этого поля. |
| [Frontend/init_page.py:1232](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:1232>) | `self._update_control(dialog["Main Cont"])` | Переразметка видимых полей ограничена формой метаданных. |
| [Frontend/init_page.py:1255](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:1255>) | `self._update_control(deadline_field)` | Ошибка ввода не затрагивает остальные элементы страницы. |
| [Frontend/init_page.py:1382](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:1382>) | `self._update_control(self.main_cont)` | Перестроен только основной список и его счётчики. |
| [Frontend/init_page.py:1530](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:1530>) | `self._update_control(self.main_cont)` | Новая карточка, прогресс и счётчики находятся в main_cont. |
| [Frontend/init_page.py:1744](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:1744>) | `self._update_control(year_date_field)` | После DatePicker обновляется только поле выбранной даты. |
| [Frontend/init_page.py:1780](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:1780>) | `self._update_control(main_cont)` | Меняется раскладка формы; при первоначальной сборке она ещё не смонтирована. |
| [Frontend/init_page.py:1799](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:1799>) | `self._update_control(entry_interval_rep)` | Подсветка ошибки ограничена полем интервала. |
| [Frontend/init_page.py:1816](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:1816>) | `self._update_control(month_day_entry)` | Подсветка ошибки ограничена полем числа месяца. |
| [Frontend/init_page.py:1826](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:1826>) | `self._update_control(year_date_field)` | Подсветка ошибки ограничена полем годовой даты. |
| [Frontend/init_page.py:1889](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:1889>) | `self._update_control(date_field)` | Выбранная дата отображается в одном поле формы. |
| [Frontend/init_page.py:1925](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:1925>) | `self._update_control(date_field)` | Отсутствующая дата отмечается только в поле даты. |
| [Frontend/init_page.py:1940](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:1940>) | `self._update_control(date_field)` | Ошибка сохранения отображается только у даты. |
| [Frontend/init_page.py:1997](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:1997>) | `self._update_control(year_date_field)` | Редактор правила меняет только поле годовой даты. |
| [Frontend/init_page.py:2015](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:2015>) | `self._update_control(dialog["Main Cont"])` | Переразметка ограничена формой редактирования правила. |
| [Frontend/init_page.py:2032](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:2032>) | `self._update_control(entry_interval)` | Ошибка интервала не требует обновления списка за формой. |
| [Frontend/init_page.py:2043](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:2043>) | `self._update_control(month_day_entry)` | Обновляется только поле с ошибкой числа месяца. |
| [Frontend/init_page.py:2048](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:2048>) | `self._update_control(year_date_field)` | Обновляется только поле с отсутствующей годовой датой. |
| [Frontend/init_page.py:2094](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:2094>) | `self._update_control(date_field)` | Редактор отложенного дела меняет только поле даты. |
| [Frontend/init_page.py:2127](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:2127>) | `self._update_control(date_field)` | Ошибка в редакторе относится только к отсутствующей дате. |
| [Frontend/init_page.py:2139](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:2139>) | `self._update_control(date_field)` | Ошибка изменения даты не затрагивает всю страницу. |
| [Frontend/init_page.py:2812](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:2812>) | `self._update_control(copy_status)` | Результат копирования меняет только текст статуса. |
| [Frontend/init_page.py:2823](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:2823>) | `self._update_control(content)` | Индикатор и доступность кнопок находятся внутри формы общей группы. |
| [Frontend/init_page.py:2841](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/init_page.py:2841>) | `self._update_control(content)` | Ошибка и восстановленные кнопки относятся к той же форме. |
| [Frontend/settings.py:246](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/settings.py:246>) | `self._update_controls(switch, status)` | Настройка шифрования меняет только переключатель и его подпись. |
| [Frontend/settings.py:256](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/settings.py:256>) | `self._update_controls(switch, status)` | Состояние ожидания ограничено этими двумя контролами. |
| [Frontend/settings.py:269](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/settings.py:269>) | `self._update_controls(switch, status)` | Результат операции не меняет другие разделы настроек. |
| [Frontend/settings.py:312](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/settings.py:312>) | `self._update_controls(content)` | Видимость полей и кнопки меняется только в разделе пароля. |
| [Frontend/settings.py:320](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/settings.py:320>) | `self._update_controls(status)` | Несовпадение паролей меняет только сообщение об ошибке. |
| [Frontend/settings.py:325](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/settings.py:325>) | `self._update_controls(content)` | Блокировка ввода ограничена разделом пароля. |
| [Frontend/settings.py:350](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/settings.py:350>) | `self._update_controls(content)` | После сохранения обновляются поля, переключатель и статус раздела. |
| [Frontend/settings.py:495](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/settings.py:495>) | `self._update_controls(btn_backup, backup_status)` | Отправка бэкапа меняет только свою кнопку и статус. |
| [Frontend/settings.py:513](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/settings.py:513>) | `self._update_controls(btn_backup, backup_status)` | Завершение выгрузки возвращает доступность той же кнопки. |
| [Frontend/settings.py:533](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/settings.py:533>) | `self._update_controls(import_button, export_button, status)` | Импорт и экспорт меняют только свои кнопки и сообщение. |
| [Frontend/settings.py:799](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/artifacts/stage2/before/Frontend/settings.py:799>) | `self._update_controls(row)` | Подпись и пункт меню принадлежат одной строке повторяющегося дела. |

Diff только этапа 2: [bench_stage2.diff](<C:/НУЖНОЕ/Программирование/Python-scripts2/To-do list — копия/bench_stage2.diff>).
