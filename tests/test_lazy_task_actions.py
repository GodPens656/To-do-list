"""Проверки ленивого меню и границ обновления карточки дела."""

from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import flet as ft
import pytest

from Frontend.task_actions import TaskActionsMenu
from test_ui_state import make_front
from test_ui_performance import serialize


def menu_for(card):
    """Находит меню, не создавая его пункты для проверки начального дерева."""
    pending = [card]
    while pending:
        control = pending.pop()
        if isinstance(control, TaskActionsMenu):
            return control
        pending.extend(getattr(control, 'controls', []))
        content = getattr(control, 'content', None)
        if isinstance(content, ft.Control):
            pending.append(content)
    raise AssertionError('Меню карточки не найдено')


def seed(front, count):
    data = front.back._load()
    data['tasks'] = [dict(id=str(index), name=f'Дело {index}', status=False,
                          group='default', created_date='10-11-2026') for index in range(count)]
    front.back.store.save_all_sections(data)
    front.render_daily_repeat_tasks()
    return [control for control in front.tasks_cont.content.controls if isinstance(control.data, str)]


def test_thousand_cards_have_no_menu_items_until_opened():
    front = make_front()
    cards = seed(front, 1000)
    assert all(menu_for(card).items == [] for card in cards)
    menu = menu_for(cards[500])
    items = menu.build_items()
    assert len(items) == 4
    assert sum(len(menu_for(card).items) for card in cards) == 4
    assert menu.build_items() is items
    front.render_daily_repeat_tasks()
    assert next(control for control in front.tasks_cont.content.controls if control.key == '500') is cards[500]


@pytest.mark.parametrize('effect', ('none', 'liquid_glass_half', 'liquid_glass'))
@pytest.mark.parametrize('phone', (False, True))
@pytest.mark.parametrize('show_checkbox', (False, True))
def test_lazy_menu_preserves_items_bindings_and_theme(effect, phone, show_checkbox):
    front = make_front(effect=effect, phone=phone)
    copy, repeat, edit, delete = Mock(), Mock(), Mock(), Mock()
    card, delete_target, edit_target, text, checkbox = front.utils.create_row_with_task(
        'Текст', False, 'record-id', show_checkbox=show_checkbox, on_copy=copy, on_repeat=repeat,
    )
    menu = menu_for(card)
    edit_target.on_click, delete_target.on_click = edit, delete
    edit_target.tooltip = 'Редактировать запись'
    assert menu.items == []
    assert menu.content.data == 'record-id'
    assert menu.secondary_trigger is menu.tertiary_trigger is None
    items = menu.build_items()
    assert [item.content for item in items] == [
        'Редактировать', 'Скопировать', *(['Сделать повторяющимися'] if show_checkbox else []), 'Удалить',
    ]
    assert items[0].tooltip == 'Редактировать запись'
    assert items[0].on_click is edit and items[-1].on_click is delete
    assert items[1].on_click is copy
    if show_checkbox:
        assert items[2].on_click is repeat
    assert isinstance(checkbox, ft.Checkbox) is show_checkbox
    assert all(item.icon.size == 18 for item in items)
    assert all(item.label_text_style.size == front.utils.libs.text_size(14) for item in items)
    appearance = card.content.controls[-1 if phone else 0]
    original = front.utils.libs.prepare(ft.PopupMenuButton(icon_color=front.utils.libs.FletIconColor))
    themed = appearance.theme.popup_menu_theme
    assert (themed.color, themed.shape, themed.shadow_color, themed.elevation) == (
        original.bgcolor, original.shape, original.shadow_color, original.elevation,
    )
    front.libs.prepare(card)
    assert not hasattr(menu.content, '_nd_glass_skin')
    assert menu.content.style is None


@pytest.mark.asyncio
@pytest.mark.parametrize('phone', (False, True))
async def test_first_click_updates_items_before_native_open_and_reuses_them(phone):
    front = make_front(phone=phone)
    menu = menu_for(seed(front, 1)[0])
    events = []

    async def opened(**kwargs):
        assert len(menu.items) == 4
        assert kwargs['local_position'] == ft.Offset(48 if phone else 0, 0)
        events.append('open')

    with patch.object(TaskActionsMenu, 'update', side_effect=lambda: events.append('update')), \
            patch.object(ft.ContextMenu, 'open', new_callable=AsyncMock, side_effect=opened):
        await menu.content.on_click(Mock(control=menu.content))
        items = tuple(menu.items)
        await menu.content.on_click(Mock(control=menu.content))
    assert events == ['update', 'open', 'update', 'open']
    assert all(before is after for before, after in zip(items, menu.items))


@pytest.mark.parametrize('effect', ('none', 'liquid_glass_half', 'liquid_glass'))
def test_checkbox_patch_skips_other_cards_and_preserves_glass_undo(effect):
    front = make_front(effect=effect)
    cards = seed(front, 150)
    page = ft.Page(sess=Mock(), web=False)
    page.views[0].controls = [front.main_cont]
    serialize(page, initial=True)
    unchanged_patch = serialize(page)
    row = cards[0]
    checkbox = next(control for control in row.content.controls if isinstance(control, ft.Checkbox))
    with patch.object(front, '_update_control') as update, patch.object(ft.Control, 'update'):
        checkbox.value = True
        checkbox.on_change(Mock(control=checkbox))
    update.assert_called_once_with(row, front.task_overview)
    assert front.back.get_task(row.key)['status'] is True
    assert not front.undo_btn.disabled
    if effect == 'liquid_glass':
        assert front.undo_btn._nd_glass_skin.opacity == 1
    with patch.object(ft.Text, 'before_update', autospec=True) as visited:
        serialize(row)
        serialize(front.task_overview)
    assert all(call.args[0].value != 'Дело 149' for call in visited.call_args_list)
    # Кнопка undo имеет собственное обновление из callback слоя данных.
    serialize(front.undo_btn)
    # Сравниваем с неизменённым экраном: его прежние служебные патчи стилей
    # не должны скрывать пропущенное изменение других контролов.
    assert serialize(page) == unchanged_patch


def test_settings_security_updates_only_changed_controls():
    front = make_front()
    widgets, load = front.utils2.build_widgets_for_account_encryption(front.page)
    front.cloud.read_user_data_text.return_value = ''
    password = front.utils2.build_widgets_for_security(front.page)
    switch = password.controls[0]
    front.page.update.reset_mock()
    switch.value = True
    switch.on_change(None)
    front.page.update.assert_called_once_with(password)
    assert password.controls[2].visible is False
    assert password.controls[3].visible is True


def test_metadata_updates_form_visibility_and_only_invalid_field():
    front = make_front()
    front._update_control = Mock()
    dialog = front.libs.widgets_for_ask_task('Текст', 'Сохранить', 'Дело')
    values = front._add_task_metadata_controls(dialog, deadline_as_days=True)
    section = dialog['Main Cont'].content.controls[-3]
    tile = section if isinstance(section, ft.ExpansionTile) else section.content
    controls = tile.controls[0].controls
    selector = next(control.controls[0] for control in controls
                    if isinstance(control, ft.Row)
                    and isinstance(control.controls[0], ft.Dropdown)
                    and control.controls[0].label is None)
    field = next(control for control in controls if isinstance(control, ft.TextField)
                 and control.label == 'Дедлайн через (дней)')
    selector.value = 'deadline'
    selector.on_select(None)
    front._update_control.assert_called_once_with(dialog['Main Cont'])
    front._update_control.reset_mock()
    field.value = '0'
    assert values() is None
    front._update_control.assert_called_once_with(field)


def test_date_picker_can_reopen_after_updating_only_selected_date_field():
    from flet.utils.object_model import patch_dataclass

    front = make_front()
    front._update_control = Mock()
    dialog = front.libs.widgets_for_ask_task('Текст', 'Сохранить', 'Дело')
    front._add_task_metadata_controls(dialog)
    picker = front.page.overlay[-1]
    page = ft.Page(sess=Mock(), web=False)
    page.views[0].controls = [dialog['Main Cont']]
    page.overlay.append(picker)
    serialize(page, initial=True)
    picker.open = True
    serialize(picker)
    # Клиент Flet обновляет свойства без записи серверного изменения.
    patch_dataclass(picker, {'open': False, 'value': datetime(2026, 11, 11)})
    picker.on_change(Mock(control=picker, data='2026-11-11'))
    field = front._update_control.call_args.args[0]
    assert isinstance(field, ft.TextField)
    assert field.value == '11-11-2026'
    serialize(field)
    picker.open = True
    assert any(operation.get('value') is True for operation in serialize(picker))
