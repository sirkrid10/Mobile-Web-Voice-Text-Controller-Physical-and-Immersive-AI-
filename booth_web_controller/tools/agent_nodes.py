#!/usr/bin/env python3
"""Terminal fallback: status, stop-all, kill-all, or enable next-start automatic mode."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent_runtime import RuntimeRegistry, identity

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('command', choices=['status', 'stop-all', 'kill-all', 'automatic'])
parser.add_argument('--workspace', type=Path, required=True, help='Same AGENT_WORKSPACE used by Backend')
args = parser.parse_args()
registry = RuntimeRegistry(args.workspace)
if args.command in ('stop-all', 'kill-all'):
    result = registry.fallback_manual(force=args.command == 'kill-all')
elif args.command == 'automatic':
    with registry.transaction():
        registry.write('preferences.json', {'manual': False, 'disabled': []})
    result = {'mode': 'automatic', 'message': 'Restart Backend or press Open in Staff to start nodes'}
else:
    result = {'preferences': registry.preferences(), 'processes': {
        name: {**record, 'alive': identity(record.get('pid')) == record.get('start_ticks') and record.get('start_ticks') is not None}
        for name, record in registry.read('processes.json', {}).items()
    }, 'directory': str(registry.directory)}
print(json.dumps(result, ensure_ascii=False, indent=2))
