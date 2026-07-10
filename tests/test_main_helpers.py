import os
from datetime import date
from pathlib import Path

import main
import ftrack


class FakeSettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def value(self, key, default='', type=str):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value


def test_parse_startup_args_extracts_data_root():
    root, cleaned = main.parse_startup_args([
        'FRESH.exe',
        '--style',
        'fusion',
        '--data-root',
        r'D:\Fresh Data',
    ])

    assert root == Path(r'D:\Fresh Data')
    assert cleaned == ['FRESH.exe', '--style', 'fusion']


def test_launch_argv_for_current_app_quotes_data_root():
    argv = main._launch_argv_for_current_app(
        r'D:\Fresh Data',
        executable=r'C:\Python311\pythonw.exe',
        script_path=Path(r'D:\Apps\FRESH App\main.py'),
        frozen=False,
    )
    command = main._format_windows_command(argv)

    assert argv == [
        r'C:\Python311\pythonw.exe',
        r'D:\Apps\FRESH App\main.py',
        '--data-root',
        r'D:\Fresh Data',
    ]
    assert '"D:\\Apps\\FRESH App\\main.py"' in command
    assert '"D:\\Fresh Data"' in command


def test_launch_argv_for_frozen_app_omits_script():
    argv = main._launch_argv_for_current_app(
        r'D:\Fresh Data',
        executable=r'C:\Program Files\FRESH\FRESH.exe',
        frozen=True,
    )

    assert argv == [
        r'C:\Program Files\FRESH\FRESH.exe',
        '--data-root',
        r'D:\Fresh Data',
    ]


def test_configured_data_root_override_updates_settings_and_env(tmp_path):
    settings = FakeSettings()
    old_env = os.environ.get(main.DATA_ROOT_ENV)
    root = tmp_path / 'Fresh Data'

    try:
        resolved = main.configured_data_root(settings, root)

        assert resolved == root
        assert settings.values[main.DATA_ROOT_SETTINGS] == str(root)
        assert os.environ[main.DATA_ROOT_ENV] == str(root)
    finally:
        if old_env is None:
            os.environ.pop(main.DATA_ROOT_ENV, None)
        else:
            os.environ[main.DATA_ROOT_ENV] = old_env


def test_attachment_recovery_key_prefers_real_tracking_id():
    att = {
        'id': 'att1',
        'type': 'file_ref',
        'tracking': {
            'tracking_id': 'real-tag',
            'content_hash': 'abc',
            'size_snapshot': 12,
        },
    }

    assert main._attachment_recovery_key(att) == ('real-tag', True)


def test_attachment_recovery_key_allows_hash_only_files():
    att = {
        'id': 'att2',
        'type': 'file_ref',
        'tracking': {
            'content_hash': 'abc',
            'size_snapshot': 12,
        },
    }

    assert main._attachment_recovery_key(att) == ('hash:att2', False)


def test_attachment_recovery_key_rejects_hash_only_folders():
    att = {
        'id': 'att3',
        'type': 'folder',
        'tracking': {
            'content_hash': 'abc',
            'size_snapshot': 12,
        },
    }

    assert main._attachment_recovery_key(att) == ('', False)


def test_clear_recovery_failure_removes_backoff_state():
    att = {
        'recovery_failed_at': 123.0,
        'recovery_failed_count': 4,
        'other': 'kept',
    }

    assert main._clear_recovery_failure(att) is True
    assert att == {'other': 'kept'}
    assert main._clear_recovery_failure(att) is False


def test_build_tracking_snapshot_is_read_only(monkeypatch):
    token = (1, 2, 3, 4, 5, 6)
    calls = []
    monkeypatch.setattr(main, '_path_identity_snapshot', lambda _path: token)

    def fake_build(path, tracking_id=None, *, write_identity=True):
        calls.append((path, tracking_id, write_identity))
        return {'tracking_id': tracking_id or 'generated', 'content_hash': 'abc'}

    monkeypatch.setattr(main.ftrack, 'build_tracking', fake_build)

    result = main._build_tracking_snapshot('D:/docs/a.txt', 'old-id', token)

    assert result == ({'tracking_id': 'old-id', 'content_hash': 'abc'}, token)
    assert calls == [('D:/docs/a.txt', 'old-id', False)]


def test_build_tracking_snapshot_rejects_schedule_time_replacement(monkeypatch):
    monkeypatch.setattr(main, '_path_identity_snapshot', lambda _path: ('new',))

    def forbidden_build(*_args, **_kwargs):
        raise AssertionError('stale queued work must not inspect the replacement')

    monkeypatch.setattr(main.ftrack, 'build_tracking', forbidden_build)

    assert main._build_tracking_snapshot('D:/docs/a.txt', expected_identity=('old',)) is None


def test_build_tracking_snapshot_rejects_change_during_hash(monkeypatch):
    tokens = iter([('before',), ('after',)])
    monkeypatch.setattr(main, '_path_identity_snapshot', lambda _path: next(tokens))
    monkeypatch.setattr(
        main.ftrack,
        'build_tracking',
        lambda *_args, **_kwargs: {'tracking_id': 'generated'},
    )

    assert main._build_tracking_snapshot('D:/docs/a.txt') is None


def test_finalize_tracking_identity_handles_failed_tag_write(monkeypatch):
    monkeypatch.setattr(main.ftrack, 'write_tracking_tag', lambda *_args: False)

    fresh = main._finalize_tracking_identity(
        'D:/docs/a.txt',
        {'tracking_id': 'generated', 'content_hash': 'abc'},
    )
    existing = main._finalize_tracking_identity(
        'D:/docs/a.txt',
        {'tracking_id': 'generated', 'content_hash': 'abc'},
        old_tracking_id='old-id',
    )

    assert fresh == {'content_hash': 'abc'}
    assert existing['tracking_id'] == 'old-id'


def test_combined_shell_rename_event_is_processed_bitwise():
    class Harness:
        def __init__(self):
            self.moves = []

        def _apply_shell_move(self, old_path, new_path):
            self.moves.append((old_path, new_path))

    harness = Harness()
    code = main.SHCNE_RENAMEITEM | main.SHCNE_UPDATEITEM

    main.MainWindow._process_shell_event(harness, code, r'D:\Old\a.txt', r'E:\New\a.txt')

    assert harness.moves == [
        (
            os.path.normcase(os.path.normpath(r'D:\Old\a.txt')),
            os.path.normcase(os.path.normpath(r'E:\New\a.txt')),
        )
    ]


def test_tag_scan_rejects_multiple_verified_copies(monkeypatch):
    paths = [(r'D:\copy-a.txt', False), (r'E:\copy-b.txt', False)]
    monkeypatch.setattr(ftrack, '_iter_disk', lambda *_args, **_kwargs: iter(paths))
    monkeypatch.setattr(
        ftrack,
        '_read_tracking_tag_known_kind',
        lambda *_args, **_kwargs: 'same-tag',
    )
    emitted = []

    found = ftrack.scan_for_tags(
        {'same-tag'},
        unique_only=True,
        on_found=lambda tag, path: emitted.append((tag, path)),
    )

    assert found == {}
    assert emitted == []


def test_tag_scan_deduplicates_same_path_from_overlapping_roots(monkeypatch):
    paths = [(r'D:\same.txt', False), (r'D:\same.txt', False)]
    monkeypatch.setattr(ftrack, '_iter_disk', lambda *_args, **_kwargs: iter(paths))
    monkeypatch.setattr(
        ftrack,
        '_read_tracking_tag_known_kind',
        lambda *_args, **_kwargs: 'same-tag',
    )

    found = ftrack.scan_for_tags({'same-tag'}, unique_only=True)

    assert found == {'same-tag': r'D:\same.txt'}


def test_everything_tag_scan_rejects_multiple_verified_copies(monkeypatch):
    monkeypatch.setattr(
        ftrack,
        'everything_search',
        lambda *_args, **_kwargs: [r'D:\copy-a.txt', r'E:\copy-b.txt'],
    )
    monkeypatch.setattr(ftrack, 'read_tracking_tag', lambda *_args, **_kwargs: 'same-tag')

    found = ftrack.scan_via_everything(
        {'same-tag': 'document.txt'},
        drive_hints=['D'],
    )

    assert found == {}


def test_auto_recovery_updates_all_attachments_sharing_tracking_id():
    class FakeStorage:
        def __init__(self):
            self.attachments = {
                'a': {'id': 'a', 'recovery_failed_at': 1},
                'b': {'id': 'b', 'recovery_failed_count': 2},
            }

        def find_attachment(self, att_id):
            return {'id': f'note-{att_id}'}, self.attachments.get(att_id)

        def adopt_external_path(self, attachment, path):
            attachment['original_path'] = path

    class Harness:
        def __init__(self):
            self.storage = FakeStorage()
            self.current_note_id = None
            self._auto_recovered_tags = set()

    harness = Harness()

    main.MainWindow._on_auto_recovery_found(
        harness,
        'shared-tag',
        r'E:\Moved\document.txt',
        {'shared-tag': ['a', 'b']},
    )

    assert harness._auto_recovered_tags == {'shared-tag'}
    for attachment in harness.storage.attachments.values():
        assert attachment['original_path'] == r'E:\Moved\document.txt'
        assert 'recovery_failed_at' not in attachment
        assert 'recovery_failed_count' not in attachment


def test_auto_recovery_backoff_schedule_caps_at_one_hour():
    assert main._auto_recovery_backoff_seconds(0) == 180.0
    assert main._auto_recovery_backoff_seconds(1) == 180.0
    assert main._auto_recovery_backoff_seconds(2) == 600.0
    assert main._auto_recovery_backoff_seconds(3) == 1800.0
    assert main._auto_recovery_backoff_seconds(4) == 3600.0
    assert main._auto_recovery_backoff_seconds(99) == 3600.0


def test_heatmap_historical_range_anchors_to_latest_record():
    latest = date(2024, 2, 10)
    today = date(2026, 7, 10)

    assert main.heatmap_end_date(latest, today, weeks=20) == latest


def test_heatmap_recent_range_stays_anchored_to_today():
    latest = date(2026, 7, 8)
    today = date(2026, 7, 10)

    assert main.heatmap_end_date(latest, today, weeks=20) == today


def test_timeline_detail_list_respects_exact_category_filter():
    records = [{'id': 'all'}]
    active = [{'id': 'filtered'}]

    result = main.TimelineDialog._timeline_records_for_list(object(), records, active)

    assert result == active


def test_timeline_category_chart_keeps_context_but_ranking_filters():
    records = [{'id': 'all'}]
    active = [{'id': 'filtered'}]
    method = main.TimelineDialog._chart_records

    assert method(object(), records, active, '工作', '工作', 'category') == records
    assert method(object(), records, active, '工作', '工作', 'ranking') == active
