"""Feedback persistence — ORM and SQL repository."""

from vassilflow.persistence.feedback.model import FeedbackRow
from vassilflow.persistence.feedback.sql import FeedbackRepository

__all__ = ["FeedbackRepository", "FeedbackRow"]
