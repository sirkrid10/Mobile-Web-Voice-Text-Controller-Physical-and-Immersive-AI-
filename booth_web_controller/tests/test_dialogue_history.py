import asyncio
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.dialogue_history import DialogueHistory
from app.models import IntentOutcome, TextCommandRequest
from app.session_manager import SessionManager
from app.vr_subtitle import VRSubtitleHub


def test_history_persists_bounds_and_redacts_without_recording_tokens(tmp_path):
    path = tmp_path / 'history.sqlite3'
    history = DialogueHistory(path, secrets=('private-api-token',))
    history.capacity = 3
    for index in range(5):
        history.record('request', text=f'{index} private-api-token', session_token='never-record-this', request_id=str(index))
    result = history.snapshot()
    assert [e['request_id'] for e in result['events']] == ['2', '3', '4']
    assert 'private-api-token' not in json.dumps(result)
    assert 'never-record-this' not in json.dumps(result)
    assert path.stat().st_mode & 0o777 == 0o600
    history.close()
    reopened = DialogueHistory(path)
    assert len(reopened.snapshot()['events']) == 3
    reopened.close()


def test_history_unavailable_does_not_raise_on_record_or_read(tmp_path):
    blocker = tmp_path / 'not-a-directory'
    blocker.write_text('file')
    history = DialogueHistory(blocker / 'history.sqlite3')
    history.record('request', text='test')
    assert history.snapshot()['available'] is False
    assert history.snapshot()['events'] == []
    history.close()


def test_history_api_requires_pin_and_bounds_limit(tmp_path, monkeypatch):
    history = DialogueHistory(tmp_path / 'history.sqlite3')
    monkeypatch.setattr(main, 'dialogue_history', history)
    history.record('subtitle', text='<script>unsafe</script>', request_id='review-1')
    client = TestClient(main.app)
    assert client.get('/api/v1/staff/history').status_code == 401
    headers = {'X-Staff-Pin': settings.STAFF_PIN}
    for limit in (0, 2001):
        assert client.get(f'/api/v1/staff/history?limit={limit}', headers=headers).status_code == 422
    response = client.get('/api/v1/staff/history?limit=1', headers=headers)
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['events'][0]['text'] == '<script>unsafe</script>'
    history.close()


def test_request_intent_and_subtitle_correlate_even_without_vr_client(tmp_path, monkeypatch):
    history = DialogueHistory(tmp_path / 'history.sqlite3')
    manager = SessionManager()
    manager.auto_return_enabled = False
    manager.set_history_callback(main.record_dialogue)
    monkeypatch.setattr(main, 'dialogue_history', history)
    monkeypatch.setattr(main, 'session_manager', manager)
    monkeypatch.setattr(main, 'vr_subtitles', VRSubtitleHub())

    class Bridge:
        def publish_user_transcript(self, **values):
            outcome = IntentOutcome(request_id=values['request_id'], session_id=values['session_id'],
                stamp={'sec': 1, 'nanosec': 0}, status='UNSUPPORTED', message='ไม่ใช่คำสั่งเดินทาง')
            assert manager.record_intent_result(outcome)
            main.receive_subtitle('ผมชาร์จแบตแทนกินข้าวครับ', 1, values['request_id'])

    monkeypatch.setattr(main, 'ros_bridge_instance', Bridge())
    async def run():
        claim = await manager.claim('review-session')
        await main.command_text(TextCommandRequest(text='นายกินข้าวหรือยัง'),
            x_session_token=claim['session_token'], x_session_id='review-session')
    asyncio.run(run())
    events = history.snapshot()['events']
    assert [event['kind'] for event in events] == ['request', 'intent', 'subtitle']
    assert len({event['request_id'] for event in events}) == 1
    before = len(events)
    main.receive_subtitle('', 2)
    assert len(history.snapshot()['events']) == before
    history.close()


def test_logging_failure_does_not_prevent_command_or_vr_delivery(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError('fake disk error')
    broken = SimpleNamespace(record=fail, error=None)
    monkeypatch.setattr(main, 'dialogue_history', broken)
    monkeypatch.setattr(main, 'vr_subtitles', VRSubtitleHub())
    main.record_web_request('req', 'session', 'hello', 'text')
    main.receive_subtitle('ทดสอบ', 1, 'req')
    assert broken.error == 'history_write_failed'
    assert json.loads(main.vr_subtitles.latest)['text'] == 'ทดสอบ'
