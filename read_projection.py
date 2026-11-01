"""Short-lived memoization for explicitly opted-in, read-only responses.

No process-global or cross-request results are retained. Writers use the same
helpers without this scope, so approvals and release gates always re-read their
evidence. Mutable response containers are copied; SQLAlchemy row identities are
retained only inside this session and are never deep-copied.
"""
from contextlib import contextmanager
from functools import wraps
from inspect import signature

from sqlalchemy import event


_KEY = 'fabtrace_read_projection'


def _copy(value):
    if isinstance(value, dict):
        return {key: _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy(item) for item in value)
    if isinstance(value, set):
        return {_copy(item) for item in value}
    # Dates, strings and numbers are immutable. ORM rows must remain attached
    # to their real session; callers only read them inside an opted-in GET.
    return value


def _state(s):
    state = s.info.get(_KEY)
    if state is None or not state['enabled']:
        return None
    if s.new or s.dirty or s.deleted:
        state['enabled'] = False
        state['values'].clear()
        return None
    return state


@contextmanager
def read_projection(s):
    """Enable reuse only for this explicit read scope; nested readers share it.

Any attempted flush, DML, or transaction boundary disables reuse for the rest
of the outer scope. This is defense in depth: mutating routes must not opt in.
"""
    if _KEY in s.info:
        yield s
        return
    state = {'enabled': not bool(s.new or s.dirty or s.deleted), 'values': {}}
    s.info[_KEY] = state

    def invalidate(*args):
        state['enabled'] = False
        state['values'].clear()

    def statement(execution):
        if not execution.is_select:
            invalidate()

    listeners = [('before_flush', invalidate), ('after_commit', invalidate),
                 ('after_rollback', invalidate), ('after_soft_rollback', invalidate),
                 ('do_orm_execute', statement)]
    for name, callback in listeners:
        event.listen(s, name, callback)
    try:
        yield s
    finally:
        for name, callback in listeners:
            event.remove(s, name, callback)
        state['values'].clear()
        s.info.pop(_KEY, None)


def read_cached(key):
    """Memoize a pure helper only when its caller entered read_projection."""
    def decorate(function):
        namespace = function.__module__ + '.' + function.__qualname__

        @wraps(function)
        def wrapped(s, *args, **kwargs):
            state = _state(s)
            if state is None:
                return function(s, *args, **kwargs)
            identity = namespace, key(s, *args, **kwargs)
            if identity not in state['values']:
                result = function(s, *args, **kwargs)
                if _state(s) is not state:
                    return result
                state['values'][identity] = _copy(result)
            return _copy(state['values'][identity])

        return wrapped
    return decorate


def reader_role(user):
    """Receiving permission projections depend on the passed role, not auth."""
    return getattr(user, 'role', user)


def read_response(function):
    """Opt one GET handler in without altering its FastAPI call signature."""
    parameters = signature(function)

    @wraps(function)
    def wrapped(*args, **kwargs):
        s = parameters.bind(*args, **kwargs).arguments['s']
        with read_projection(s):
            return function(*args, **kwargs)

    return wrapped
