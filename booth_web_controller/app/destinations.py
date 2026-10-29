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
STATION_SPEECH_HINT = (
    'จุด A จุดเอ โซนกู้ภัย RESCUE ZONE SEARCH & RESCUE; '
    'จุด B จุดบี โซนการแพทย์ MEDICAL ZONE MEDICAL AID; '
    'จุด C จุดซี โซนส่งเสบียง SUPPLY ZONE SUPPLY DROP-OFF; '
    'จุด D จุดดี ศูนย์บัญชาการ COMMAND CENTER MISSION CONTROL; '
    'กลับจุดเริ่มต้น return to start คือจุด D'
)


def visitor_locations():
    return [{
        'id': station['id'], 'label': f"📍 จุด {station['id']} · {station['name']}",
        'prompt': f"ไป{station['name']}",
        'description': f"{station['english']} · {station['corner']}", 'icon': 'map-pin',
    } for station in STATIONS] + [
        {'id': 'start', 'label': '🏠 กลับจุดเริ่มต้น (จุด D · ศูนย์บัญชาการ)',
         'prompt': 'กลับจุดเริ่มต้น', 'description': 'กลับ D ศูนย์บัญชาการ มุมล่างขวา', 'icon': 'home'},
        {'id': 'wait', 'label': '⏸️ ส่งคำขอรอ (ยังไม่รองรับ)', 'prompt': 'หยุดรอตรงนี้ก่อน',
         'description': 'ส่งคำขอรอผ่านระบบแปลคำสั่ง (ยังไม่รองรับ)', 'icon': 'pause'},
    ]
