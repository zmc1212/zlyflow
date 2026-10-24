"""A request/task-local model choice; never changes provider settings."""
from contextlib import contextmanager
from contextvars import ContextVar

_MODEL: ContextVar[str | None] = ContextVar("director_assistant_model", default=None)


def current_model() -> str | None:
    return _MODEL.get()


@contextmanager
def model_scope(model_id: str | None):
    token = _MODEL.set(model_id)
    try:
        yield
    finally:
        _MODEL.reset(token)
