"""Minimal server that serves the UI and generates LiveKit tokens."""

import json
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from livekit.api import AccessToken, VideoGrants

LIVEKIT_API_KEY = "devkey"
LIVEKIT_API_SECRET = "secret"
PORT = 3000
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
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"token": token}).encode())
        else:
            super().do_GET()


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"UI running at http://localhost:{PORT}")
    server.serve_forever()
