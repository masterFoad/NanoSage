# backend/utils/log_streaming.py

import logging
import asyncio
import re
import sys
import io
import os
from pathlib import Path
from typing import Optional, Callable
from datetime import datetime, timezone


class LogStreamHandler(logging.Handler):
    """
    Custom logging handler that streams logs to WebSocket clients.
    Thread-safe implementation that works with async callbacks.
    """

    def __init__(self, query_id: str, callback: Optional[Callable] = None, loop: Optional[asyncio.AbstractEventLoop] = None):
        super().__init__()
        self.query_id = query_id
        self.callback = callback
        self.loop = loop  # Store the event loop reference
        self.log_buffer = []
        self.max_buffer_size = 100

    def emit(self, record):
        """
        Emit a log record - DISABLED for frontend streaming.
        We ONLY want print() statements that start with [INFO] or [DEBUG].
        All logging.info/debug/warning calls from libraries are ignored.
        """
        # Block ALL logging framework messages from going to frontend
        return

    def get_logs(self):
        """Get all buffered logs"""
        return self.log_buffer.copy()


class PrintCapture(io.TextIOBase):
    """Capture print() statements and send them to the log handler"""

    def __init__(self, query_id: str, callback: Optional[Callable] = None, loop: Optional[asyncio.AbstractEventLoop] = None, original_stdout=None, debug: bool = False):
        self.query_id = query_id
        self.callback = callback
        self.loop = loop
        self.original_stdout = original_stdout
        self.buffer = ""
        self.log_buffer = []
        self.max_buffer_size = 100
        self.debug = debug
        self.project_root = str(Path(__file__).parent.parent.parent.resolve())

    def write(self, text):
        """Capture written text"""
        if self.original_stdout:
            self.original_stdout.write(text)

        self.buffer += text

        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            line = line.strip()

            if line and self.callback and re.match(r'^\[(INFO|DEBUG)\]', line, re.IGNORECASE):
                friendly_log = self._make_user_friendly(line)

                if friendly_log:
                    log_message = {
                        'query_id': self.query_id,
                        'status': 'processing',
                        'message': friendly_log,
                        'timestamp': datetime.utcnow().isoformat()
                    }

                    self.log_buffer.append(log_message)
                    if len(self.log_buffer) > self.max_buffer_size:
                        self.log_buffer.pop(0)

                    if self.callback and self.loop:
                        try:
                            if self.debug:
                                from datetime import datetime as dt_now
                                print(f"[SEND-DEBUG] Sending: {friendly_log[:50]}", file=sys.__stderr__, flush=True)

                            future = asyncio.run_coroutine_threadsafe(self.callback(log_message), self.loop)

                            if self.debug:
                                def check_result(fut):
                                    try:
                                        fut.result()
                                        print(f"[SEND-DEBUG] ✓ Sent successfully", file=sys.__stderr__, flush=True)
                                    except Exception as e:
                                        print(f"[SEND-DEBUG] ✗ Failed: {e}", file=sys.__stderr__, flush=True)
                                future.add_done_callback(check_result)
                        except Exception as e:
                            if self.debug:
                                print(f"[SEND-DEBUG] ✗ Exception: {e}", file=sys.__stderr__, flush=True)

        return len(text)

    def flush(self):
        """Flush buffer"""
        if self.original_stdout:
            self.original_stdout.flush()

    def _make_user_friendly(self, log_entry: str) -> Optional[str]:
        """Convert [INFO] or [DEBUG] print messages to clean format for frontend display"""
        log_entry = re.sub(r'^\[(INFO|DEBUG)\]\s*', '', log_entry, flags=re.IGNORECASE)
        log_entry = log_entry.replace('\\', '/')

        if self.project_root:
            normalized_root = self.project_root.replace('\\', '/')
            log_entry = log_entry.replace(normalized_root + '/', '')
            log_entry = log_entry.replace(normalized_root, '')

        log_entry = re.sub(r'results/[\w-]+/', 'results/', log_entry)
        log_entry = re.sub(r'[A-Z]:/Users/[^/]+/', '', log_entry)
        log_entry = re.sub(r'/home/[^/]+/', '', log_entry)
        log_entry = re.sub(r'/Users/[^/]+/', '', log_entry)
        log_entry = log_entry.strip()

        return log_entry if log_entry else None

    def get_logs(self):
        """Get all buffered logs"""
        return self.log_buffer.copy()


def setup_log_streaming(query_id: str, callback: Optional[Callable] = None, loop: Optional[asyncio.AbstractEventLoop] = None, debug: bool = False) -> tuple:
    """Set up log streaming for a query"""
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

    handler = LogStreamHandler(query_id, callback, loop)
    handler.setLevel(logging.CRITICAL + 1)
    handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG)

    original_stdout = sys.stdout
    print_capture = PrintCapture(query_id, callback, loop, original_stdout, debug=debug)
    sys.stdout = print_capture

    return (handler, print_capture, original_stdout)


def cleanup_log_streaming(handler_tuple):
    """Remove log streaming handler and restore stdout"""
    if not handler_tuple:
        return

    handler, print_capture, original_stdout = handler_tuple

    # Restore stdout
    sys.stdout = original_stdout

    # Remove logging handler
    root_logger = logging.getLogger()
    root_logger.removeHandler(handler)
