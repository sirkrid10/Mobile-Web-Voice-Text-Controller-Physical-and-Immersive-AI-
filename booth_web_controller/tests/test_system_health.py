"""Connectivity labels distinguish observation, response, freshness and display."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import time

import pytest

from app.system_health import SystemHealth, tailscale_health
from app.vr_subtitle import VRSubtitleHub


def test_tailscale_online_is_distinct_from_peer_reachability(monkeypatch):
    probe = AsyncMock(side_effect=[(0, json.dumps({
        'BackendState': 'Running', 'TailscaleIPs': ['100.1.1.1'],
        'Peer': {'vm': {'TailscaleIPs': ['100.2.2.2'], 'Online': True}},
    })), (1, '')])
    monkeypatch.setattr('app.system_health.run_probe', probe)
    result = asyncio.run(tailscale_health('100.2.2.2'))
    assert result['status'] == 'connected'
    assert result['server_online'] is True
    assert result['reachable'] is False


@pytest.mark.parametrize('response', [(None, ''), (1, ''), (0, 'not json')])
def test_probe_failure_is_unknown_not_offline(monkeypatch, response):
    monkeypatch.setattr('app.system_health.run_probe', AsyncMock(return_value=response))
    assert asyncio.run(tailscale_health('100.2.2.2'))['status'] == 'unknown'


def test_robot_health_uses_live_source_time_not_cached_poll_time():
    now = time.time()
    observation = {'robot_received_at': now, 'robot_source_at': now}
    bridge = SimpleNamespace(robot_observation=lambda: observation)
    processes = SimpleNamespace(snapshot=lambda: {})
    hub = VRSubtitleHub()
    health = SystemHealth(bridge, processes, hub)
    health.latest['ros'] = {'robot_received_at': now - 20, 'robot_source_at': now - 20}
    assert health.snapshot()['ros']['robot_fresh'] is True
    observation['robot_source_at'] = now - 20
    assert health.snapshot()['ros']['robot_fresh'] is False
    observation['robot_source_at'] = now + 10
    assert health.snapshot()['ros']['robot_fresh'] is False
    observation['robot_source_at'] = None
    assert health.snapshot()['ros']['robot_fresh'] is False


def test_vr_published_caption_is_not_a_display_ack():
    hub = VRSubtitleHub()
    hub.publish('ทดสอบ', time.time())
    status = hub.inspection()
    assert status['connections'] == 0
    assert status['last_published_at']
    assert status['last_sent_at'] is None
    assert status['display_confirmed'] is False
