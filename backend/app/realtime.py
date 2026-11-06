"""Live seat map: every browser watching a show gets seat changes over a WebSocket.

Services return a list of changes like {"show_id": 1, "seat_id": 7, "status": "held"}
*after* their transaction commits; routers hand them to `hub.publish`.
"""
from collections import defaultdict

from fastapi import WebSocket


class Hub:
    def __init__(self):
        self.rooms: dict[int, set[WebSocket]] = defaultdict(set)

    async def join(self, show_id: int, ws: WebSocket) -> None:
        await ws.accept()
        self.rooms[show_id].add(ws)

    def leave(self, show_id: int, ws: WebSocket) -> None:
        self.rooms[show_id].discard(ws)

    async def publish(self, changes: list[dict]) -> None:
        by_show: dict[int, list[dict]] = defaultdict(list)
        for c in changes:
            by_show[c["show_id"]].append({"seat_id": c["seat_id"], "status": c["status"]})
        for show_id, seats in by_show.items():
            for ws in list(self.rooms.get(show_id, ())):
                try:
                    await ws.send_json({"type": "seats", "seats": seats})
                except Exception:  # browser closed the tab
                    self.leave(show_id, ws)


hub = Hub()
