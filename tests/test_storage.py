"""storage / crypter / accounts 的核心数据安全测试。

storage.py 是唯一决定用户数据存亡的模块且不依赖 Qt，可直接单测。
支持两种运行方式：
    python -m pytest tests/test_storage.py -q
    python tests/test_storage.py          （无 pytest 时的简易自跑）
"""
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from accounts import AccountManager  # noqa: E402
from crypter import MAGIC, Crypter, PasswordCrypter, SaltFileError  # noqa: E402
from cryptography.fernet import InvalidToken  # noqa: E402
from storage import SCREENSHOT_BOARD_ID, Storage, is_attachment_image  # noqa: E402


def make_store(tmp_path):
    return Storage(app_dir=tmp_path / 'data')


def write_png(path: Path, payload: bytes = b'fake-png-bytes-0123456789') -> bytes:
    path.write_bytes(payload)
    return payload


# ---------- 基础 CRUD 往返 ----------

def test_note_crud_roundtrip(tmp_path):
    store = make_store(tmp_path)
    note = store.create_note(category='工作')
    note_id = note['id']
    store.update_note(note_id, title='标题', content='<p>正文</p>')

    reloaded = Storage(app_dir=tmp_path / 'data')
    loaded = reloaded.get_note(note_id)
    assert loaded and loaded['title'] == '标题'
    assert loaded.get('category') == '工作'

    assert reloaded.delete_note(note_id)
    assert reloaded.get_note(note_id).get('deleted') is True
    assert any(
        item.get('note', {}).get('id') == note_id for item in reloaded.deleted_items()
    )
    assert reloaded.restore_note(note_id)
    assert not reloaded.get_note(note_id).get('deleted')
    assert reloaded.hard_delete_note(note_id)
    assert reloaded.get_note(note_id) is None


def test_data_file_encrypted_on_disk(tmp_path):
    store = make_store(tmp_path)
    store.create_note()
    raw = store.data_file.read_bytes()
    assert raw.startswith(MAGIC), 'data.json 必须落盘为密文'


# ---------- 附件生命周期 ----------

def test_attachment_encrypt_and_trash_flow(tmp_path):
    store = make_store(tmp_path)
    note = store.create_note()
    src = tmp_path / 'pic.png'
    payload = write_png(src)

    att = store.add_attachment(note['id'], src, copy=True)
    assert att and att['type'] == 'file'
    stored = store.attachments_dir / att['stored_name']
    assert stored.exists() and stored.read_bytes().startswith(MAGIC)
    assert store.read_attachment_bytes(att) == payload
    assert is_attachment_image(att)

    # path_for 解到临时缓存目录，内容为明文原文
    resolved = store.path_for(att)
    assert Path(resolved).read_bytes() == payload

    # 软删除 → trash/；恢复 → attachments/；彻底删除 → 全部消失
    assert store.remove_attachment(note['id'], att['id'])
    assert not stored.exists()
    assert (store.trash_dir / att['stored_name']).exists()
    assert store.restore_attachment(att['id'])
    assert stored.exists()
    assert store.hard_remove_attachment(note['id'], att['id'])
    assert not stored.exists()
    assert not (store.trash_dir / att['stored_name']).exists()


def test_plain_attachment_migration_and_marker(tmp_path):
    app_dir = tmp_path / 'data'
    (app_dir / 'attachments').mkdir(parents=True)
    plain = app_dir / 'attachments' / 'legacy.png'
    plain.write_bytes(b'plain-legacy-bytes')
    leftover = app_dir / 'attachments' / 'old.png.enc.tmp'
    leftover.write_bytes(b'broken-half-written')

    store = Storage(app_dir=app_dir)
    blob = plain.read_bytes()
    assert blob.startswith(MAGIC), '历史明文附件应在启动时被加密'
    assert store.crypter.decrypt_bytes(blob) == b'plain-legacy-bytes'
    assert not leftover.exists(), '上次迁移残留的 .enc.tmp 应被清掉'
    assert (app_dir / '.attachments_encrypted').exists(), '完成后应写跳过标记'


# ---------- 数据损坏只读保护 ----------

def test_corrupt_data_enters_readonly(tmp_path):
    app_dir = tmp_path / 'data'
    app_dir.mkdir(parents=True)
    corrupt = MAGIC + b'definitely-not-a-fernet-token'
    (app_dir / 'data.json').write_bytes(corrupt)

    store = Storage(app_dir=app_dir)
    assert store.load_failed, '解密失败必须进入只读保护'
    assert store.notes == [] or all(
        n.get('id') == SCREENSHOT_BOARD_ID for n in store.notes
    )
    # 任何保存都被拒绝，磁盘上的原始密文保持原样
    store.create_note()
    assert store.save() is False
    assert (app_dir / 'data.json').read_bytes() == corrupt
    backups = list(app_dir.glob('data.corrupt-*.json'))
    assert backups, '损坏文件应被留底'
    assert backups[0].read_bytes() == corrupt


def test_password_storage_rejects_plaintext_tamper(tmp_path):
    app_dir = tmp_path / 'data'
    app_dir.mkdir(parents=True)
    # 攻击者把密码账户的 data.json 整体替换成明文 JSON
    (app_dir / 'data.json').write_text(json.dumps([{'id': 'evil'}]), encoding='utf-8')
    crypter = PasswordCrypter('correct-horse-battery', os.urandom(32), 60_000)
    store = Storage(app_dir=app_dir, crypter=crypter)
    assert store.load_failed, '密码账户不存在合法明文，必须拒绝并保护原文件'


def test_save_failure_reports(tmp_path):
    store = make_store(tmp_path)
    store.create_note()
    failures = []
    store.on_save_failed = failures.append

    original = store.crypter.encrypt_bytes

    def broken(_data):
        raise OSError('disk full (simulated)')

    store.crypter.encrypt_bytes = broken
    try:
        assert store.save() is False
        assert failures and 'disk full' in failures[0]
        assert 'disk full' in store.save_error
    finally:
        store.crypter.encrypt_bytes = original
    assert store.save() is True


def test_bak_rotation(tmp_path):
    store = make_store(tmp_path)
    store.create_note(category='第一版')
    first_raw = store.data_file.read_bytes()
    store.create_note(category='第二版')
    bak = store.data_file.with_suffix('.json.bak')
    assert bak.exists(), '覆盖前应保留上一版备份'
    assert bak.read_bytes() == first_raw


# ---------- 批量落盘 ----------

def test_batch_writes_once(tmp_path):
    store = make_store(tmp_path)
    calls = []
    original = store._write_data_file

    def counting():
        calls.append(1)
        return original()

    store._write_data_file = counting
    with store.batch():
        for _ in range(5):
            store.create_note()
    assert len(calls) == 1, 'batch 内 5 次 save 应合并为一次落盘'
    assert len([n for n in store.notes if n.get('id') != SCREENSHOT_BOARD_ID]) == 5


# ---------- 密钥文件保护 ----------

def test_corrupt_salt_raises_instead_of_silent_rebuild(tmp_path):
    app_dir = tmp_path / 'data'
    app_dir.mkdir(parents=True)
    (app_dir / '.fkey').write_bytes(b'short')  # 半写损坏
    try:
        Crypter(app_dir)
    except SaltFileError:
        pass
    else:
        raise AssertionError('损坏的盐文件必须报错，不能静默重建')
    assert list(app_dir.glob('.fkey.corrupt-*')), '损坏盐应留底'


def test_password_crypter_rejects_plaintext(tmp_path):
    crypter = PasswordCrypter('pw', os.urandom(32), 60_000)
    try:
        crypter.decrypt_bytes(b'plain bytes without magic')
    except InvalidToken:
        pass
    else:
        raise AssertionError('密码加密器不能把明文当作合法内容')


def test_stale_cache_dir_swept(tmp_path):
    stale = Path(tempfile.gettempdir()) / f'FRESH-cache-stale-{uuid.uuid4().hex[:8]}'
    stale.mkdir()
    (stale / 'leak.png').write_bytes(b'plaintext leak')
    store = make_store(tmp_path)
    assert not stale.exists(), '上次崩溃残留的明文缓存目录应被清扫'
    assert store.cache_dir.exists()


# ---------- 账户两阶段重加密 ----------

def _seed_account(tmp_path):
    manager = AccountManager(app_root=tmp_path / 'root')
    account, crypter = manager.create_account('测试', '')
    acc_dir = manager.account_dir(account)
    (acc_dir / 'attachments').mkdir(parents=True, exist_ok=True)
    data = crypter.encrypt_bytes(json.dumps([{'id': 'n1'}]).encode('utf-8'))
    (acc_dir / 'data.json').write_bytes(data)
    blob = crypter.encrypt_bytes(b'attachment-bytes')
    (acc_dir / 'attachments' / 'a.png').write_bytes(blob)
    return manager, account, crypter


def test_set_and_clear_password_roundtrip(tmp_path):
    manager, account, crypter = _seed_account(tmp_path)
    password = 'a-strong-password-123'
    account, new_crypter = manager.set_account_password(account, crypter, password)

    unlocked, unlocked_crypter = manager.unlock(password)
    assert unlocked and unlocked['id'] == account['id']
    acc_dir = manager.account_dir(account)
    payload = unlocked_crypter.decrypt_bytes((acc_dir / 'data.json').read_bytes())
    assert json.loads(payload) == [{'id': 'n1'}]
    att = unlocked_crypter.decrypt_bytes((acc_dir / 'attachments' / 'a.png').read_bytes())
    assert att == b'attachment-bytes'
    assert not account.get('pending_rekey')
    assert not list(acc_dir.rglob('*.rekey-tmp'))

    account, machine_crypter = manager.clear_account_password(account, new_crypter)
    again, again_crypter = manager.unlock_passwordless(account['id'])
    assert again and again_crypter
    payload = again_crypter.decrypt_bytes((acc_dir / 'data.json').read_bytes())
    assert json.loads(payload) == [{'id': 'n1'}]


def test_rekey_resume_after_commit_crash(tmp_path):
    """模拟提交阶段（纯重命名）中途崩溃：重启后无需密码即可续传完成。"""
    import base64

    manager, account, crypter = _seed_account(tmp_path)
    acc_dir = manager.account_dir(account)
    password = 'resume-password-456'
    salt = os.urandom(32)
    new_crypter = PasswordCrypter(password, salt)
    verifier = new_crypter.encrypt_bytes(
        ('FRESH_ACCOUNT_VERIFIER:' + account['id']).encode('utf-8')
    )
    pending = {
        'kind': 'password',
        'salt': base64.urlsafe_b64encode(salt).decode('ascii'),
        'iterations': 600_000,
        'verifier': base64.urlsafe_b64encode(verifier).decode('ascii'),
        'started_at': 'x',
    }
    account['pending_rekey'] = pending
    manager._replace_account(account)
    # 新密文已写好 .rekey-tmp、提交标记存在、但重命名一半都没来得及做
    for rel in ('data.json', 'attachments/a.png'):
        path = acc_dir / rel
        plain = crypter.decrypt_bytes(path.read_bytes())
        path.with_name(path.name + '.rekey-tmp').write_bytes(new_crypter.encrypt_bytes(plain))
    (acc_dir / '.rekey-commit').write_text('x', encoding='utf-8')

    resumed = AccountManager(app_root=tmp_path / 'root')
    unlocked, unlocked_crypter = resumed.unlock(password)
    assert unlocked and unlocked['id'] == account['id'], '续传后新密码应可登录'
    payload = unlocked_crypter.decrypt_bytes((acc_dir / 'data.json').read_bytes())
    assert json.loads(payload) == [{'id': 'n1'}]
    assert not list(acc_dir.rglob('*.rekey-tmp'))
    assert not (acc_dir / '.rekey-commit').exists()
    assert not resumed.get_account(account['id']).get('pending_rekey')


def test_rekey_rollback_before_commit(tmp_path):
    """未进入提交阶段就崩溃：原文件未动，应整体回滚到无密码状态。"""
    import base64

    manager, account, crypter = _seed_account(tmp_path)
    acc_dir = manager.account_dir(account)
    pending = {
        'kind': 'password',
        'salt': base64.urlsafe_b64encode(os.urandom(32)).decode('ascii'),
        'iterations': 600_000,
        'verifier': base64.urlsafe_b64encode(b'x').decode('ascii'),
        'started_at': 'x',
    }
    account['pending_rekey'] = pending
    manager._replace_account(account)
    (acc_dir / 'data.json.rekey-tmp').write_bytes(b'half-done')

    resumed = AccountManager(app_root=tmp_path / 'root')
    refreshed = resumed.get_account(account['id'])
    assert not refreshed.get('pending_rekey'), '应回滚 pending'
    assert not list(acc_dir.rglob('*.rekey-tmp')), '旁路副本应清除'
    unlocked, unlocked_crypter = resumed.unlock_passwordless(account['id'])
    assert unlocked and unlocked_crypter, '回滚后旧（无密码）状态应完好'
    payload = unlocked_crypter.decrypt_bytes((acc_dir / 'data.json').read_bytes())
    assert json.loads(payload) == [{'id': 'n1'}]


# ---------- 简易自跑（无 pytest 环境时） ----------

if __name__ == '__main__':
    import inspect
    import shutil as _shutil
    import traceback

    failures = 0
    tests = [
        (name, fn) for name, fn in sorted(globals().items())
        if name.startswith('test_') and inspect.isfunction(fn)
    ]
    for name, fn in tests:
        workdir = Path(tempfile.mkdtemp(prefix='fresh-test-'))
        try:
            fn(workdir)
            print(f'PASS {name}')
        except Exception:
            failures += 1
            print(f'FAIL {name}')
            traceback.print_exc()
        finally:
            _shutil.rmtree(workdir, ignore_errors=True)
    print(f'\n{len(tests) - failures}/{len(tests)} passed')
    sys.exit(1 if failures else 0)
