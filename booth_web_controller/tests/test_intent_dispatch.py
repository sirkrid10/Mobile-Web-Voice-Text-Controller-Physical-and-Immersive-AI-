"""Sender evidence belongs to exactly one current visitor request."""

import asyncio

from app.models import IntentDispatchOutcome, IntentOutcome, RosStamp
from app.session_manager import SessionManager


def test_dispatch_correlates_before_intent_and_resets_with_request_and_session():
    async def run():
        manager = SessionManager()
        manager.auto_return_enabled = False
        claim = await manager.claim('visitor')
        request_id, session_id = await manager.begin_user_request('visitor', claim['session_token'])
        event = IntentDispatchOutcome(
            request_id=request_id, session_id=session_id,
            stamp=RosStamp(sec=42, nanosec=0), destination_id='B', status='sent',
        )
        assert not manager.record_intent_dispatch(event.model_copy(update={'request_id': 'old'}))
        assert not manager.record_intent_dispatch(event.model_copy(update={'session_id': 'other'}))
        assert manager.record_intent_dispatch(event)
        assert manager.record_intent_result(IntentOutcome(
            request_id=request_id, session_id=session_id, stamp=event.stamp,
            destination_id='B', status='NAVIGATE',
        ))
        state = manager.get_state_broadcast()
        assert state.latest_request_id == request_id
        assert state.latest_intent_dispatch == event
        assert not manager.record_intent_dispatch(event.model_copy(update={'status': 'unknown'}))
        await manager.begin_user_request('visitor', claim['session_token'])
        assert manager.get_state_broadcast().latest_intent_dispatch is None
        assert not manager.record_intent_dispatch(event)
        await manager.release_session(reason='test')
        state = manager.get_state_broadcast()
        assert state.latest_request_id is None
        assert state.latest_intent_dispatch is None
        assert not manager.record_intent_dispatch(event)

    asyncio.run(run())
