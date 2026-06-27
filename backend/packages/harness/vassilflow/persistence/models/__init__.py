"""ORM model registration entry point.

Importing this module ensures all ORM models are registered with
``Base.metadata`` so Alembic autogenerate detects every table.

The actual ORM classes have moved to entity-specific subpackages:
- ``vassilflow.persistence.thread_meta``
- ``vassilflow.persistence.run``
- ``vassilflow.persistence.feedback``
- ``vassilflow.persistence.user``

``RunEventRow`` remains in ``vassilflow.persistence.models.run_event`` because
its storage implementation lives in ``vassilflow.runtime.events.store.db`` and
there is no matching entity directory.
"""

from vassilflow.persistence.channel_connections.model import (
    ChannelConnectionRow,
    ChannelConversationRow,
    ChannelCredentialRow,
    ChannelOAuthStateRow,
)
from vassilflow.persistence.feedback.model import FeedbackRow
from vassilflow.persistence.models.run_event import RunEventRow
from vassilflow.persistence.run.model import RunRow
from vassilflow.persistence.thread_meta.model import ThreadMetaRow
from vassilflow.persistence.user.model import UserRow

__all__ = [
    "ChannelConnectionRow",
    "ChannelConversationRow",
    "ChannelCredentialRow",
    "ChannelOAuthStateRow",
    "FeedbackRow",
    "RunEventRow",
    "RunRow",
    "ThreadMetaRow",
    "UserRow",
]
