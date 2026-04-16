"""Minimal server that serves the UI and generates LiveKit tokens."""

import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from dotenv import load_dotenv
from livekit.api import AccessToken, VideoGrants

load_dotenv()

LIVEKIT_URL = os.environ["LIVEKIT_URL"]
LIVEKIT_EXTERNAL_URL = os.getenv("LIVEKIT_EXTERNAL_URL", LIVEKIT_URL)
LIVEKIT_API_KEY = os.environ["LIVEKIT_API_KEY"]
LIVEKIT_API_SECRET = os.environ["LIVEKIT_API_SECRET"]
PORT = int(os.getenv("UI_PORT", "3000"))
UI_DIR = Path(__file__).parent


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def do_GET(self):
        if self.path == "/api/token":
            token = (
                AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
                .with_identity("user")
                .with_grants(VideoGrants(room_join=True, room="test-room"))
                .to_jwt()
            )
            payload = {"token": token, "url": LIVEKIT_EXTERNAL_URL}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())
        else:
            super().do_GET()


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"UI running at http://localhost:{PORT}")
    server.serve_forever()
