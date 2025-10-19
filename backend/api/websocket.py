# backend/api/websocket.py

from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Set
import json
import asyncio


class ConnectionManager:
    """Manages WebSocket connections for real-time updates"""

    def __init__(self, debug: bool = False):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.connection_queries: Dict[WebSocket, str] = {}
        self.debug = debug

    async def connect(self, websocket: WebSocket, query_id: str):
        """Accept a new WebSocket connection for a query"""
        await websocket.accept()

        if query_id not in self.active_connections:
            self.active_connections[query_id] = set()

        self.active_connections[query_id].add(websocket)
        self.connection_queries[websocket] = query_id

        if self.debug:
            from datetime import datetime
            print(f"[WebSocket] Client connected: {query_id}", flush=True)

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection"""
        if websocket in self.connection_queries:
            query_id = self.connection_queries[websocket]

            if query_id in self.active_connections:
                self.active_connections[query_id].discard(websocket)
                if len(self.active_connections[query_id]) == 0:
                    del self.active_connections[query_id]

            del self.connection_queries[websocket]

            if self.debug:
                print(f"[WebSocket] Client disconnected: {query_id}")

    async def send_progress_update(self, query_id: str, message: dict):
        """Send a progress update to all clients listening to a query"""
        if query_id not in self.active_connections:
            if self.debug:
                print(f"[WS-DEBUG] No connection for {query_id[:8]}", flush=True)
            return

        json_message = json.dumps(message)

        if self.debug:
            msg_preview = message.get('message', '')[:50] if isinstance(message, dict) else str(message)[:50]
            print(f"[WS-DEBUG] Sending to {len(self.active_connections[query_id])} clients: {msg_preview}", flush=True)

        disconnected = set()
        for connection in self.active_connections[query_id]:
            try:
                await connection.send_text(json_message)
            except Exception as e:
                print(f"[WebSocket] Error sending message: {e}")
                disconnected.add(connection)

        for connection in disconnected:
            self.disconnect(connection)

    async def send_log(self, query_id: str, log_message: dict):
        """Send a log message to all clients listening to a query"""
        await self.send_progress_update(query_id, log_message)

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients"""
        json_message = json.dumps(message)

        for query_id, connections in self.active_connections.items():
            disconnected = set()
            for connection in connections:
                try:
                    await connection.send_text(json_message)
                except Exception as e:
                    print(f"[WebSocket] Error broadcasting: {e}")
                    disconnected.add(connection)

            for connection in disconnected:
                self.disconnect(connection)


# Global connection manager
manager = ConnectionManager()
