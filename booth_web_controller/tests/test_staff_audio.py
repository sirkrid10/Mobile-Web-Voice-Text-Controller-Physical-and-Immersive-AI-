from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.session_manager import SessionManager


@pytest.fixture
def audio_api(monkeypatch):
    monkeypatch.setattr(settings, 'STT_PREPROCESS_AUDIO', False)
    monkeypatch.setattr(main, 'session_manager', SessionManager())
    monkeypatch.setattr(main, 'system_health', SimpleNamespace(snapshot=lambda: {
        'audio': main.stt_service.preprocessing_status(),
    }))
    monkeypatch.setattr('app.stt_service.shutil.which', lambda _: '/test/ffmpeg')
    return TestClient(main.app), {'X-Staff-Pin': settings.STAFF_PIN}


def test_audio_switch_requires_pin_and_rejects_invalid_payloads(audio_api):
    client, headers = audio_api
    assert client.post('/api/v1/staff/system/audio', json={'enabled': True}).status_code == 401
    for payload in ({}, {'enabled': 'false'}, {'enabled': True, 'command': 'restart'}):
        assert client.post('/api/v1/staff/system/audio', headers=headers, json=payload).status_code == 422
    assert settings.STT_PREPROCESS_AUDIO is False


def test_audio_switch_changes_only_runtime_flag_and_returns_confirmed_status(audio_api):
    client, headers = audio_api
    prompt = settings.STT_INITIAL_PROMPT
    identity = main.session_manager.latest_request_identity
    for enabled in (True, False):
        response = client.post('/api/v1/staff/system/audio', headers=headers, json={'enabled': enabled})
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.json()['audio'] == {'enabled': enabled, 'ffmpeg_available': True}
        assert settings.STT_PREPROCESS_AUDIO is enabled
        assert settings.STT_INITIAL_PROMPT == prompt
        assert main.session_manager.latest_request_identity == identity


def test_missing_ffmpeg_cannot_enable_but_can_disable(audio_api, monkeypatch):
    client, headers = audio_api
    monkeypatch.setattr('app.stt_service.shutil.which', lambda _: None)
    response = client.post('/api/v1/staff/system/audio', headers=headers, json={'enabled': True})
    assert response.status_code == 409
    assert settings.STT_PREPROCESS_AUDIO is False
    monkeypatch.setattr(settings, 'STT_PREPROCESS_AUDIO', True)
    response = client.post('/api/v1/staff/system/audio', headers=headers, json={'enabled': False})
    assert response.status_code == 200
    assert response.json()['audio'] == {'enabled': False, 'ffmpeg_available': False}


def test_audio_switch_does_not_mutate_when_inspection_is_unavailable(audio_api, monkeypatch):
    client, headers = audio_api
    monkeypatch.setattr(main, 'system_health', None)
    assert client.post('/api/v1/staff/system/audio', headers=headers, json={'enabled': True}).status_code == 503
    assert settings.STT_PREPROCESS_AUDIO is False
