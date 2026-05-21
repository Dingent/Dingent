import os

import uvicorn

from .app import create_app

app = create_app()


def start():
    """Launches the Uvicorn server."""
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "dingent.server.main:app",
        host="0.0.0.0",
        port=port,
    )
