import asyncio
import time
from typing import Optional, Dict
from dataclasses import dataclass, field
from enum import Enum


class SessionState(Enum):
    IDLE = "idle"
    WAITING_FILE = "waiting_file"
    WAITING_PROXY = "waiting_proxy"
    CHECKING = "checking"
    DONE = "done"


@dataclass
class UserSession:
    """Per-user session data."""
    user_id: int
    chat_id: int
    state: SessionState = SessionState.IDLE
    check_task: Optional[asyncio.Task] = None
    total_cookies: int = 0
    checked_count: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    banned_count: int = 0
    robux_total: int = 0
    premium_count: int = 0
    start_time: float = 0.0
    last_progress_update: float = 0.0
    results_message_id: Optional[int] = None
    cookies: list = field(default_factory=list)
    cancel_requested: bool = False

    @property
    def cps(self) -> float:
        if self.start_time == 0:
            return 0
        elapsed = time.time() - self.start_time
        if elapsed == 0:
            return 0
        return self.checked_count / elapsed

    @property
    def progress_percent(self) -> float:
        if self.total_cookies == 0:
            return 0
        return (self.checked_count / self.total_cookies) * 100


class SessionManager:
    """Manages per-user sessions for the Telegram bot."""

    def __init__(self):
        self._sessions: Dict[int, UserSession] = {}
        self._lock = asyncio.Lock()

    async def get_session(self, user_id: int, chat_id: int) -> UserSession:
        """Get or create a session for a user."""
        async with self._lock:
            if user_id not in self._sessions:
                self._sessions[user_id] = UserSession(user_id=user_id, chat_id=chat_id)
            return self._sessions[user_id]

    async def remove_session(self, user_id: int):
        """Remove a user's session."""
        async with self._lock:
            if user_id in self._sessions:
                del self._sessions[user_id]

    async def set_state(self, user_id: int, state: SessionState):
        """Update session state."""
        async with self._lock:
            if user_id in self._sessions:
                self._sessions[user_id].state = state

    async def get_state(self, user_id: int) -> SessionState:
        """Get current session state."""
        async with self._lock:
            if user_id in self._sessions:
                return self._sessions[user_id].state
            return SessionState.IDLE

    def get_active_sessions_count(self) -> int:
        """Count of currently checking sessions."""
        return sum(1 for s in self._sessions.values() if s.state == SessionState.CHECKING)

    def is_user_checking(self, user_id: int) -> bool:
        """Check if a user is currently running a check."""
        if user_id in self._sessions:
            return self._sessions[user_id].state == SessionState.CHECKING
        return False