"""Auth + identity + DB. Everything account-shaped lives here.

Public surface (importers should `from auth import X`, not reach into
submodules):
  - flows: signup, login, JWT issue/decode, typed errors
  - db: connection pool + User/Avatar dataclasses + CRUD
  - identity: SessionIdentity (the seam where "who is this user?" enters)

Re-exports below are the entire intended API. Anything not re-exported
is package-private — fair game to refactor without notice to callers.
"""

from .db import (  # noqa: F401
    Avatar,
    Db,
    User,
    get_db,
    init_db,
)
from .flows import (  # noqa: F401
    AuthError,
    InvalidCredentials,
    InvalidToken,
    UsernameTaken,
    WeakPassword,
    decode_session_token,
    issue_session_token,
    login,
    signup,
    user_id_from_token,
)
from .identity import (  # noqa: F401
    SessionIdentity,
    UserIdentity,  # back-compat alias
)
