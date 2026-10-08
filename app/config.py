"""Runtime configuration, read entirely from environment variables.

Copy ``.env.example`` to ``.env`` and adjust for your deployment. Every
setting has a sane development default so the service runs out of the box.
"""

import os


class Settings:
    """All knobs the hub exposes. Instantiated once per process."""

    def __init__(self) -> None:
        # Bearer-ish token every WebSocket client must pass as ?token=...
        self.hub_token: str = os.getenv("HUB_TOKEN", "dev-token-change-me")
        # Secret for the admin HTTP endpoints (broadcast, shutdown stats)
        self.admin_token: str = os.getenv("ADMIN_TOKEN", "dev-admin-change-me")
        # How many past messages a room keeps and replays to new joiners
        self.max_history: int = int(os.getenv("MAX_HISTORY", "50"))
        # Simple per-connection rate limit: N messages per window seconds
        self.rate_limit_messages: int = int(os.getenv("RATE_LIMIT_MESSAGES", "20"))
        self.rate_limit_window: float = float(os.getenv("RATE_LIMIT_WINDOW", "10.0"))
        self.port: int = int(os.getenv("PORT", "8000"))

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"Settings(port={self.port}, max_history={self.max_history}, "
            f"rate_limit={self.rate_limit_messages}/{self.rate_limit_window}s)"
        )


settings = Settings()
