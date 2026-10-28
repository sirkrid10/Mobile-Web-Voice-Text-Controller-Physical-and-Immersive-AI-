#!/usr/bin/env python3
"""Read the Backend subtitle WebSocket without sending robot commands."""

import argparse
import asyncio
import json

import websockets


async def watch(url, once=False):
    async with websockets.connect(url, max_size=16_384, open_timeout=5) as socket:
        async for raw in socket:
            print(json.dumps(json.loads(raw), ensure_ascii=False), flush=True)
            if once:
                return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', help='ws://BACKEND_IP:8000/ws/vr/subtitle')
    parser.add_argument('--once', action='store_true', help='Read one snapshot and exit')
    args = parser.parse_args()
    try:
        asyncio.run(watch(args.url, args.once))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
