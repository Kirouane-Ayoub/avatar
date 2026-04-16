from livekit.api import AccessToken, VideoGrants

token = AccessToken("devkey", "secret") \
    .with_identity("user") \
    .with_grants(VideoGrants(room_join=True, room="test-room"))
print(token.to_jwt())
