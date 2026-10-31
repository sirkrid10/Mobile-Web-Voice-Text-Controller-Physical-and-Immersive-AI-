"""Station names from the 2026-10-29 signs; Robot owns all coordinates."""

STATIONS = (
    {'id': 'A', 'name': 'โซนกู้ภัย', 'english': 'RESCUE ZONE / SEARCH & RESCUE',
     'aliases': ('โซนกู้ภัย', 'กู้ภัย', 'rescue zone', 'search & rescue', 'search and rescue'), 'corner': 'มุมล่างซ้าย'},
    {'id': 'B', 'name': 'โซนการแพทย์', 'english': 'MEDICAL ZONE / MEDICAL AID',
     'aliases': ('โซนการแพทย์', 'การแพทย์', 'medical zone', 'medical aid', 'ปฐมพยาบาล'), 'corner': 'มุมบนซ้าย'},
    {'id': 'C', 'name': 'โซนส่งเสบียง', 'english': 'SUPPLY ZONE / SUPPLY DROP-OFF',
     'aliases': ('โซนส่งเสบียง', 'ส่งเสบียง', 'เสบียง', 'supply zone', 'supply drop-off'), 'corner': 'มุมบนขวา'},
    {'id': 'D', 'name': 'ศูนย์บัญชาการ', 'english': 'COMMAND CENTER / MISSION CONTROL',
     'aliases': ('ศูนย์บัญชาการ', 'บัญชาการ', 'command center', 'mission control'), 'corner': 'มุมล่างขวา'},
)
DESTINATION_IDS = tuple(station['id'] for station in STATIONS)
START_DESTINATION_ID = 'D'
SPOKEN_IDS = {'A': 'เอ', 'B': 'บี', 'C': 'ซี', 'D': 'ดี'}


def station_for(identifier):
    return next(station for station in STATIONS if station['id'] == identifier)


def speech_hint(start_id=START_DESTINATION_ID):
    stations = '; '.join(
        f"จุด {station['id']} จุด{SPOKEN_IDS[station['id']]} {station['name']} "
        f"{station['english'].replace(' / ', ' ')}"
        for station in STATIONS
    )
    return stations + f'; กลับจุดเริ่มต้น return to start คือจุด {start_id}'


STATION_SPEECH_HINT = speech_hint()


def visitor_locations(start_id=START_DESTINATION_ID):
    start = station_for(start_id)
    return [{
        'id': station['id'], 'label': f"📍 จุด {station['id']} · {station['name']}",
        'prompt': f"ไป{station['name']}",
        'description': f"{station['english']} · {station['corner']}", 'icon': 'map-pin',
    } for station in STATIONS] + [
        {'id': 'start', 'label': f"🏠 กลับจุดเริ่มต้น (จุด {start_id} · {start['name']})",
         'prompt': 'กลับจุดเริ่มต้น', 'description': f"กลับ {start_id} {start['name']} {start['corner']}", 'icon': 'home'},
        {'id': 'wait', 'label': '⏸️ ส่งคำขอรอ (ยังไม่รองรับ)', 'prompt': 'หยุดรอตรงนี้ก่อน',
         'description': 'ส่งคำขอรอผ่านระบบแปลคำสั่ง (ยังไม่รองรับ)', 'icon': 'pause'},
    ]
