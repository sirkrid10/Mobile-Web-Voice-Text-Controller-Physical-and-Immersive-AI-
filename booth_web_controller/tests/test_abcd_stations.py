"""Station sign names and input hints match the A/B/C/D handoff."""
import pytest
from app.config import Settings
from app.destinations import STATIONS, DESTINATION_IDS
from app.mock_ros2_bridge import MockROS2Bridge


@pytest.mark.parametrize('text,expected', [
    ('ไปโซนกู้ภัย', 'A'), ('go to rescue zone', 'A'), ('take me to SEARCH & RESCUE', 'A'),
    ('ไปโซนการแพทย์', 'B'), ('go to MEDICAL ZONE', 'B'), ('navigate to medical aid', 'B'),
    ('ไปโซนส่งเสบียง', 'C'), ('go to SUPPLY ZONE', 'C'), ('take me to SUPPLY DROP-OFF', 'C'),
    ('ไปศูนย์บัญชาการ', 'D'), ('go to COMMAND CENTER', 'D'), ('go to mission control', 'D'),
    ('ไปจุดดี', 'D'), ('พาไปจุด ดี', 'D'), ('ไปจุดD', 'D'), ('go to point D', 'D'),
    ('กลับจุดเริ่มต้น', 'D'), ('พากลับจุดเริ่มต้นหน่อย', 'D'), ('return to start', 'D'), ('กลับศูนย์บัญชาการ', 'D'),
])
def test_sign_aliases_keep_the_correct_id(text, expected):
    destination, status, _ = MockROS2Bridge._mock_intent(text)
    assert (status, destination) == ('NAVIGATE', expected)


@pytest.mark.parametrize('text', ['สวัสดี', 'ดีมาก', 'วันนี้ดีจัง', 'หุ่นดีนะ',
    'ไปโซนกู้ภัยกับศูนย์บัญชาการ', 'ไม่ไปจุดดี', 'อย่าไปจุด D', 'ไปจุด E'])
def test_no_invented_d_or_multiple_destination_dispatch(text):
    destination, status, _ = MockROS2Bridge._mock_intent(text)
    assert status != 'NAVIGATE'
    assert destination == ''


def test_old_env_speech_hint_still_includes_all_new_stations():
    config = Settings(STT_INITIAL_PROMPT='legacy A B C hint')
    assert 'legacy A B C hint' in config.STT_INITIAL_PROMPT
    for station in STATIONS:
        assert station['name'] in config.STT_INITIAL_PROMPT
        assert f"จุด {station['id']}" in config.STT_INITIAL_PROMPT
    assert config.START_BOOTH_ID == 'D'
    assert DESTINATION_IDS == ('A', 'B', 'C', 'D')


def test_backend_names_match_llm_catalog_when_available():
    destinations = pytest.importorskip('agent_pkg.catalog.destinations')
    for station, booth in zip(STATIONS, destinations.CATALOG, strict=True):
        assert station['id'] == booth.robot_id
        assert station['name'] in booth.name
        assert all(alias in booth.aliases for alias in station['aliases'])


def test_station_names_follow_the_four_photographed_signs():
    assert [(station['id'], station['name']) for station in STATIONS] == [
        ('A', 'โซนกู้ภัย'), ('B', 'โซนการแพทย์'), ('C', 'โซนส่งเสบียง'), ('D', 'ศูนย์บัญชาการ'),
    ]


def test_configured_start_updates_default_chip_and_speech_hint():
    config = Settings(START_BOOTH_ID='B', _env_file=None)
    start = next(location for location in config.LOCATIONS if location['id'] == 'start')
    assert 'จุด B' in start['label']
    assert 'โซนการแพทย์' in start['label']
    assert 'มุมบนซ้าย' in start['description']
    assert 'return to start คือจุด B' in config.STT_INITIAL_PROMPT
    assert 'return to start คือจุด D' not in config.STT_INITIAL_PROMPT


def test_explicit_location_configuration_is_preserved():
    locations = [{'id': 'B', 'label': 'Custom point', 'prompt': 'ไปจุด B'}]
    config = Settings(START_BOOTH_ID='B', LOCATIONS=locations, _env_file=None)
    assert config.LOCATIONS == locations


def test_custom_speech_prompt_keeps_context_and_adds_current_station_catalog():
    config = Settings(START_BOOTH_ID='C', STT_INITIAL_PROMPT='Visitor context', _env_file=None)
    assert config.STT_INITIAL_PROMPT.startswith('Visitor context')
    assert all(station['name'] in config.STT_INITIAL_PROMPT for station in STATIONS)
    assert 'return to start คือจุด C' in config.STT_INITIAL_PROMPT


def test_mock_return_uses_the_configured_start(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, 'START_BOOTH_ID', 'B')
    assert MockROS2Bridge._mock_intent('return to start') == ('B', 'NAVIGATE', '')
