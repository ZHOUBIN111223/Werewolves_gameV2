from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx

from src.api.main import app
from src.api.routers.matches import get_observer_service
from src.api.services.observer_service import ObserverService
from src.enums import ActionType, GamePhase
from src.events.action import Action
from src.events.async_store import GlobalEventStore
from src.events.system_event import SystemEvent


def _seed_events(game_id: str = "game_api") -> list[object]:
    return [
        SystemEvent(
            game_id=game_id,
            phase=GamePhase.SETUP,
            visibility=["all"],
            payload={"players": ["player_0", "player_1", "player_2"]},
            system_name="game_started",
        ),
        SystemEvent(
            game_id=game_id,
            phase=GamePhase.DAY_1,
            visibility=["all"],
            payload={"previous_phase": "setup", "new_phase": "day_1", "subphase": "discussion"},
            system_name="phase_advanced",
        ),
        SystemEvent(
            game_id=game_id,
            phase=GamePhase.DAY_1,
            visibility=["player_0"],
            payload={"actor": "player_0", "request_kind": "day_vote"},
            system_name="action_requested",
        ),
        Action(
            game_id=game_id,
            phase=GamePhase.DAY_1,
            visibility=["all"],
            payload={"request_kind": "day_vote", "target": "player_1"},
            actor="player_0",
            action_type=ActionType.VOTE,
            target="player_1",
            reasoning_summary="Vote the suspicious target.",
            public_speech="",
        ),
        SystemEvent(
            game_id=game_id,
            phase=GamePhase.DAY_1,
            visibility=["all"],
            payload={"voter": "player_0", "target": "player_1", "speaker": "player_0"},
            system_name="vote_recorded",
        ),
        SystemEvent(
            game_id=game_id,
            phase=GamePhase.NIGHT_1,
            visibility=["controller"],
            payload={"deaths": ["player_1"]},
            system_name="night_resolution_completed",
        ),
        SystemEvent(
            game_id=game_id,
            phase=GamePhase.DAY_1,
            visibility=["all"],
            payload={"eliminated_player": "player_1"},
            system_name="player_eliminated",
        ),
        SystemEvent(
            game_id=game_id,
            phase=GamePhase.POST_GAME,
            visibility=["all"],
            payload={"winner": "villagers"},
            system_name="game_ended",
        ),
    ]


async def _seed_store(db_path: Path) -> None:
    store = GlobalEventStore(db_path)
    await store.initialize()
    await store.append_many(_seed_events())


class ObserverApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "events.db"
        asyncio.run(_seed_store(self.db_path))
        self.service = ObserverService(self.db_path)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.tempdir.cleanup()

    def test_service_supports_filtered_queries_and_stats(self) -> None:
        timeline = asyncio.run(self.service.get_timeline("game_api", system_name="vote_recorded"))
        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0].system_name, "vote_recorded")

        public_events = asyncio.run(
            self.service.get_events_after("game_api", after_seq=0, limit=20, visible_to="all")
        )
        self.assertEqual(len(public_events.events), 6)
        self.assertTrue(all("all" in event.visibility for event in public_events.events))

        stats = asyncio.run(self.service.get_match_stats("game_api"))
        self.assertEqual(stats.total_events, 8)
        self.assertEqual(stats.counts_by_type["system"], 7)
        self.assertEqual(stats.counts_by_type["action"], 1)
        self.assertEqual(stats.counts_by_system_name["vote_recorded"], 1)
        self.assertEqual(stats.counts_by_actor["player_0"], 1)

    def test_http_routes_expose_filters_and_stats(self) -> None:
        app.dependency_overrides[get_observer_service] = lambda: self.service

        async def exercise_routes() -> None:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                matches_response = await client.get("/api/matches")
                self.assertEqual(matches_response.status_code, 200)
                matches_payload = matches_response.json()
                self.assertEqual(len(matches_payload["items"]), 1)
                self.assertEqual(matches_payload["items"][0]["total_events"], 8)

                events_response = await client.get(
                    "/api/matches/game_api/events",
                    params={"system_name": "vote_recorded", "limit": 10},
                )
                self.assertEqual(events_response.status_code, 200)
                events_payload = events_response.json()
                self.assertEqual(len(events_payload["events"]), 1)
                self.assertEqual(events_payload["events"][0]["system_name"], "vote_recorded")

                stats_response = await client.get("/api/matches/game_api/stats")
                self.assertEqual(stats_response.status_code, 200)
                stats_payload = stats_response.json()
                self.assertEqual(stats_payload["total_events"], 8)
                self.assertEqual(stats_payload["counts_by_type"]["action"], 1)

        asyncio.run(exercise_routes())


if __name__ == "__main__":
    unittest.main()
