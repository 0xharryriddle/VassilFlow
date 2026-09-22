"""VassilFlow application and domain persistence contracts.

The engine lifecycle manages SQL application data such as runs, thread
ownership, users, and feedback. Domain repositories keep their own storage
models and share only the operational readiness/inventory/migration contract.

Usage:
    from vassilflow.persistence import init_engine, close_engine, get_session_factory
"""

from vassilflow.persistence.engine import close_engine, get_engine, get_session_factory, init_engine

__all__ = ["close_engine", "get_engine", "get_session_factory", "init_engine"]
