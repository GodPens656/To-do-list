"""Создание, редактирование и показ заметок внутри группы."""

from .attachments import AttachmentEditor

class NotesMixin:
    def open_note_editor(self, note=None):
        group_id = self.current_group_id
        dialog = self.libs.widgets_for_ask_task(
            "Запишите текст заметки", "Изменить заметку" if note else "Добавить заметку",
            "Редактирование заметки" if note else "Новая заметка",
            warning_text="Не создавайте одинаковые заметки",
        )
        entry = dialog['entry_task']
        entry.label = "Текст заметки"
        entry.hint_text = ""
        entry.value = note['text'] if note else ''
        self.libs.update_text_counter(entry)
        entry.min_lines = 1
        entry.max_lines = 12
        # Enter всегда вставляет перенос; сохранение — отдельной кнопкой.
        entry.shift_enter = False
        entry.on_submit = None
        attachments = AttachmentEditor(
            self.libs, note.get('attachments') if note else None,
            back=self.back, task_id=note['id'] if note else None,
            section="notes", group_id=group_id,
        )
        dialog['Main Cont'].content.controls.insert(-1, attachments.control)

        @self._guard_attachment_quota
        def save(_):
            if not self._validate_text_length(entry):
                return
            saved = self.back.save_note(
                group_id, entry.value, note['id'] if note else None,
                attachments=attachments.values(),
            )
            if saved is None:
                entry.error = "Введите текст заметки"
                self._update_control(entry)
                return
            self.close_page()
            self.render_daily_repeat_tasks()
            self.cloud.alg_for_redact()
            self.page.update()

        dialog['btn_create_task'].on_click = save
        self.open_page(dialog['Header'], dialog['Main Cont'], dialog['cancel'], 'note')

    def _render_notes(self, group_settings):
        notes = self.back.read_notes(self.current_group_id)
        last_date = None
        for note in notes:
            created_date = note.get('created_date', '')
            if group_settings['split_by_dates'] and last_date is not None and created_date != last_date:
                self.to_task_content(self.create_date_divider())
            last_date = created_date
            card, delete, edit, text, _ = self.utils.create_row_with_task(
                self.back.auto_add_new_string(note['text']), False, note['id'],
                created_date, self.current_group_id, show_checkbox=False,
                group_settings=group_settings,
                attachments=note.get('attachments'),
            )
            card.data = note['text']
            text.selectable = True
            edit.tooltip = "Редактировать заметку"
            edit.on_click = lambda _, n=note: self.open_note_editor(n)
            delete.tooltip = "Удалить заметку"

            def delete_note(_, note_id=note['id'], group_id=self.current_group_id):
                self.back.delete_note(group_id, note_id)
                self.render_daily_repeat_tasks()
                self.cloud.alg_for_redact()
                self.page.update()

            delete.on_click = delete_note
            self.to_task_content(card)

    def _refresh_notes_overview(self, total, shown):
        self.task_summary.value = (
            f"Найдено: {shown} из {total}" if self.current_search else
            f"Заметок: {total}" if total else "Сохраните первую заметку"
        )
        self.task_summary.visible = (
            getattr(self, "show_completion_counter", True) or bool(self.current_search)
        )
        self.task_progress.visible = False
        self.task_overview.visible = self.task_heading.visible or self.task_summary.visible
        self.empty_title.value = " Ничего не найдено" if self.current_search else " Здесь пока нет заметок"
        self.empty_hint.value = (
            "Попробуйте другой текст или очистите поиск." if self.current_search else
            "Добавьте заметку — сохраните идею или важную информацию."
        )
        self.empty_state.visible = shown == 0
        if self.empty_state not in self.tasks_cont.content.controls:
            self.tasks_cont.content.controls.append(self.empty_state)
