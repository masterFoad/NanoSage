# backend/api/websocket.py

from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Set
import json
import asyncio


class ConnectionManager:
    """Manages WebSocket connections for real-time updates"""

    def __init__(self):
        # Map of query_id -> set of WebSocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # Map of WebSocket -> query_id for cleanup
        self.connection_queries: Dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, query_id: str):
        """Accept a new WebSocket connection for a query"""
        await websocket.accept()

        if query_id not in self.active_connections:
            self.active_connections[query_id] = set()

        self.active_connections[query_id].add(websocket)
        self.connection_queries[websocket] = query_id

        from datetime import datetime
        print(f"[WebSocket] Client connected for query: {query_id} at {datetime.now().strftime('%H:%M:%S.%f')}", flush=True)

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection"""
        if websocket in self.connection_queries:
            query_id = self.connection_queries[websocket]

            if query_id in self.active_connections:
                self.active_connections[query_id].discard(websocket)

                # Clean up empty query connection sets
                if len(self.active_connections[query_id]) == 0:
                    del self.active_connections[query_id]

            del self.connection_queries[websocket]
            print(f"[WebSocket] Client disconnected from query: {query_id}")

    async def send_progress_update(self, query_id: str, message: dict):
        """
        Send a progress update to all clients listening to a query

        Args:
            query_id: The query ID
            message: Progress update message (will be JSON serialized)
        """
        if query_id not in self.active_connections:
            from datetime import datetime
            print(f"[WS-DEBUG] No connection for {query_id[:8]} at {datetime.now().strftime('%H:%M:%S.%f')}", flush=True)
            return

        # Convert message to JSON
        json_message = json.dumps(message)

        from datetime import datetime
        msg_preview = message.get('message', '')[:50] if isinstance(message, dict) else str(message)[:50]
        print(f"[WS-DEBUG] Sending to {len(self.active_connections[query_id])} clients at {datetime.now().strftime('%H:%M:%S.%f')}: {msg_preview}", flush=True)

        # Send to all connected clients
        disconnected = set()
        for connection in self.active_connections[query_id]:
            try:
                await connection.send_text(json_message)
            except Exception as e:
                print(f"[WebSocket] Error sending message: {e}")
                disconnected.add(connection)

        # Clean up disconnected clients
        for connection in disconnected:
            self.disconnect(connection)

    async def send_log(self, query_id: str, log_message: dict):
        """
        Send a log message to all clients listening to a query

        Args:
            query_id: The query ID
            log_message: Log message (will be JSON serialized)
        """
        # Use the same method as progress updates
        await self.send_progress_update(query_id, log_message)

    async def broadcast(self, message: dict):
        """
        Broadcast a message to all connected clients

        Args:
            message: Message to broadcast (will be JSON serialized)
        """
        json_message = json.dumps(message)

        for query_id, connections in self.active_connections.items():
            disconnected = set()
            for connection in connections:
                try:
                    await connection.send_text(json_message)
                except Exception as e:
                    print(f"[WebSocket] Error broadcasting: {e}")
                    disconnected.add(connection)

            # Clean up disconnected clients
            for connection in disconnected:
                self.disconnect(connection)


# Global connection manager
manager = ConnectionManager()
