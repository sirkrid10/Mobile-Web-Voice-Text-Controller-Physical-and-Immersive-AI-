"""Serve the visitor script dependencies in the same order used by the UI tests."""

import asyncio
from html.parser import HTMLParser

import httpx

from app.main import app


class ScriptSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            source = dict(attrs).get('src')
            if source:
                self.sources.append(source)


def test_visitor_page_and_script_dependencies_are_served_without_starting_runtime():
    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
            page = await client.get('/')
            assert page.status_code == 200
            scripts = ScriptSources()
            scripts.feed(page.text)
            assert scripts.sources
            assert len(scripts.sources) == len(set(scripts.sources))
            assert scripts.sources[-1].split('?')[0] == '/static/app.js'
            for source in scripts.sources:
                response = await client.get(source)
                assert response.status_code == 200, source
                assert 'javascript' in response.headers['content-type']
                assert response.text.strip()

    asyncio.run(run())
