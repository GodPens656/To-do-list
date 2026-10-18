import tempfile
import unittest

from Backend.attachments import attachment_bytes, make_attachment
from Backend.shared_groups import SHARED_ROOT
import test_shared_groups as shared


class SharedNotesTests(unittest.TestCase):
    web = True
    make_client = shared.SharedGroupTests.make_client

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.disk = shared.MemoryDisk()
        self.clients = 0
        self.owner, self.cloud = self.make_client()
        self.group_id = self.owner.create_group('Идеи', group_type='notes')
        self.file = make_attachment('идея.txt', b'original')
        self.note_id = self.owner.save_note(self.group_id, 'Первая\nзаметка', attachments=[self.file])
        self.path = f'{SHARED_ROOT}/Идеи_пароль/tasks.json'

    def join(self):
        self.owner.make_group_shared(self.group_id, 'пароль')
        member, cloud = self.make_client()
        member_group = member.connect_shared_group('Идеи', 'пароль')
        return member, cloud, member_group

    def test_join_detects_type_and_preserves_files_and_local_settings(self):
        self.owner.update_group_settings(self.group_id, show_created_date=False)
        member, _, member_group = self.join()
        self.assertEqual(member.get_group_type(member_group), 'notes')
        self.assertEqual(member.read_notes(member_group), self.owner.read_notes(self.group_id))
        self.assertEqual(member.read_tasks(), [])
        self.assertTrue(member.get_group_settings(member_group)['show_created_date'])
        value = self.disk.json(self.path)
        self.assertEqual(value['type'], 'notes')
        self.assertEqual(attachment_bytes(value['notes'][0]['attachments'][0]), b'original')
        for name, password in (('идеи', 'пароль'), ('Идеи', 'неверно')):
            with self.assertRaises(ValueError):
                member.connect_shared_group(name, password)

    def test_empty_notes_group_is_detected_and_cannot_be_replaced_by_task_group(self):
        self.owner.delete_note(self.group_id, self.note_id)
        member, _, member_group = self.join()
        self.assertEqual(member.get_group_type(member_group), 'notes')
        self.assertEqual(member.read_notes(member_group), [])
        task_group = member.create_group('Идеи')
        with self.assertRaises(ValueError):
            member.make_group_shared(task_group, 'пароль')
        self.assertEqual(self.disk.json(self.path), {'type': 'notes', 'notes': []})

    def test_simultaneous_text_and_file_edits_merge_and_deletions_propagate(self):
        member, cloud, member_group = self.join()
        self.owner.save_note(self.group_id, 'Новый текст', self.note_id)
        changed_file = make_attachment('новый.txt', b'changed')
        member.save_note(member_group, 'Первая\nзаметка', self.note_id, attachments=[changed_file])
        owner_note = self.owner.save_note(self.group_id, 'От владельца')
        member_note = member.save_note(member_group, 'От участника')
        self.cloud.sync_shared_groups()
        cloud.sync_shared_groups()
        self.cloud.sync_shared_groups()
        notes = {n['id']: n for n in self.owner.read_notes(self.group_id)}
        self.assertEqual(set(notes), {self.note_id, owner_note, member_note})
        self.assertEqual(notes[self.note_id]['text'], 'Новый текст')
        self.assertEqual(notes[self.note_id]['attachments'], [changed_file])
        self.assertEqual(self.owner.read_notes(self.group_id), member.read_notes(member_group))
        member.delete_note(member_group, self.note_id)
        cloud.sync_shared_groups()
        self.cloud.sync_shared_groups()
        self.assertNotIn(self.note_id, {n['id'] for n in self.owner.read_notes(self.group_id)})

    def test_revision_race_and_edits_during_transfer_are_preserved(self):
        self.owner.make_group_shared(self.group_id, 'пароль')
        self.owner.save_note(self.group_id, 'Перед передачей', self.note_id)

        def race(path):
            value = self.disk.json(path)
            value['notes'].append({'id': 'other', 'text': 'Конкурентная заметка'})
            self.disk.put_json(path, value)

        self.disk.before_upload = race
        self.cloud.sync_shared_groups()
        self.assertEqual(len(self.owner.read_notes(self.group_id)), 2)
        self.owner.save_note(self.group_id, 'Следующая правка', self.note_id)
        self.disk.after_download = lambda _: self.owner.save_note(self.group_id, 'Во время передачи', self.note_id)
        self.cloud.sync_shared_groups()
        self.assertEqual(self.owner.read_notes(self.group_id)[0]['text'], 'Во время передачи')
        self.assertEqual(self.disk.json(self.path)['notes'][0]['text'], 'Следующая правка')
        self.cloud.sync_shared_groups()
        self.assertEqual(self.disk.json(self.path)['notes'][0]['text'], 'Во время передачи')

    def test_restart_retries_offline_deletions_and_disconnect_keeps_remote_notes(self):
        member, cloud, member_group = self.join()
        member.delete_note(member_group, self.note_id)
        member.save_note(member_group, 'Офлайн')
        self.disk.fail = True
        cloud.sync_shared_groups()
        self.disk.fail = False
        restarted, restarted_cloud = self.make_client(directory=cloud.data_dir, store=cloud.web_store)
        restarted_cloud.sync_shared_groups()
        self.assertEqual([n['text'] for n in self.disk.json(self.path)['notes']], ['Офлайн'])
        restarted.delete_group(member_group)
        restarted_cloud.sync_shared_groups()
        new_group = restarted.connect_shared_group('Идеи', 'пароль')
        self.assertEqual([n['text'] for n in restarted.read_notes(new_group)], ['Офлайн'])

    def test_account_upload_refresh_and_login_keep_shared_notes_separate(self):
        self.cloud.write_user_data_text('account~~login~~password')
        self.owner.make_group_shared(self.group_id, 'пароль')
        personal = self.owner.create_group('Личные', group_type='notes')
        self.owner.save_note(personal, 'Личная заметка', attachments=[make_attachment('personal', b'private')])
        self.cloud.upload('account', force=True)
        groups = self.disk.json('/For_to-do/account/groups.json')
        self.assertEqual(next(g for g in groups if g['id'] == self.group_id)['notes'], [])
        self.assertEqual(next(g for g in groups if g['id'] == personal)['notes'], self.owner.read_notes(personal))
        # An account refresh must keep local shared edits awaiting upload.
        self.owner.save_note(self.group_id, 'Ещё не отправлено', self.note_id)
        self.cloud.upload('account', force=True)
        self.assertTrue(self.cloud.download('account', preserve_local=True))
        self.assertEqual(self.owner.read_notes(self.group_id)[0]['text'], 'Ещё не отправлено')
        self.cloud.sync_shared_groups()
        device, device_cloud = self.make_client()
        self.assertTrue(device_cloud.download('account'))
        device_cloud.write_user_data_text('account~~login~~password')
        self.assertEqual(device.read_notes(self.group_id), [])
        device_cloud.sync_shared_groups()
        self.assertEqual(device.read_notes(self.group_id), self.owner.read_notes(self.group_id))
        # An explicit login clears the cache and resets its merge baseline.
        device_cloud.write_user_data_text('')
        self.assertTrue(device_cloud.download('account'))
        device_cloud.write_user_data_text('account~~login~~password')
        device_cloud.sync_shared_groups()
        self.assertEqual(device.read_notes(self.group_id), self.owner.read_notes(self.group_id))

    def test_invalid_remote_notes_do_not_replace_local_data(self):
        self.owner.make_group_shared(self.group_id, 'пароль')
        before = self.owner.read_notes(self.group_id)
        for notes in (None, [{'id': 'bad', 'name': 'Wrong field'}],
                      [{'id': 'same', 'text': 'one'}, {'id': 'same', 'text': 'two'}]):
            self.disk.put_json(self.path, {'type': 'notes', 'notes': notes})
            self.assertFalse(self.cloud.sync_shared_groups())
            self.assertEqual(self.owner.read_notes(self.group_id), before)


class NativeSharedNotesTests(SharedNotesTests):
    web = False


if __name__ == '__main__':
    unittest.main()
