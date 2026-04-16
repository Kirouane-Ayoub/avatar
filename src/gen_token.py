import os

from dotenv import load_dotenv
from livekit.api import AccessToken, VideoGrants

load_dotenv()

token = AccessToken(
    os.environ["LIVEKIT_API_KEY"],
    os.environ["LIVEKIT_API_SECRET"],
).with_identity("user").with_grants(VideoGrants(room_join=True, room="test-room"))

print(token.to_jwt())
