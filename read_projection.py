"""Short-lived memoization for explicitly opted-in, read-only responses.

No process-global or cross-request results are retained. Writers use the same
helpers without this scope, so approvals and release gates always re-read their
evidence. Mutable response containers are copied; SQLAlchemy row identities are
retained only inside this session and are never deep-copied.
"""
from contextlib import contextmanager
from collections import defaultdict
from functools import wraps
from inspect import signature

from sqlalchemy import event, select


_KEY = 'fabtrace_read_projection'
PROJECTION_MISSING = object()


def _copy(value):
    if isinstance(value, defaultdict):
        return defaultdict(value.default_factory, {key: _copy(item) for key, item in value.items()})
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


def projection_enabled(s):
    return _state(s) is not None


def projection_get(s, namespace, key):
    """Return a request-local batch value, including an explicit None miss."""
    state = _state(s)
    if state is None:
        return PROJECTION_MISSING
    return _copy(state['values'].get(('batch', namespace, key), PROJECTION_MISSING))


def projection_put(s, namespace, key, value):
    state = _state(s)
    if state is not None:
        state['values']['batch', namespace, key] = _copy(value)


def read_get(s, model, ident, **kwargs):
    """Reuse primed PK rows/misses only in a clean, explicit read scope.

    Locking, refresh, options and other specialized reads always retain the
    exact Session.get behavior. Mutating routes do not have a projection scope.
    """
    if kwargs or not projection_enabled(s):
        return s.get(model, ident, **kwargs)
    key = tuple(ident) if isinstance(ident, list) else ident
    if isinstance(key, dict):
        return s.get(model, ident, **kwargs)
    cached = projection_get(s, ('row', model), key)
    if cached is not PROJECTION_MISSING:
        return cached
    row = s.get(model, ident)
    projection_put(s, ('row', model), key, row)
    return row


def prime_rows(s, model, column, identities, *, options=()):
    """Load only the requested single-column PKs, in bounded SQL batches."""
    if not projection_enabled(s):
        return {}
    wanted = set(identities) - {None}
    missing = [key for key in wanted if projection_get(s, ('row', model), key) is PROJECTION_MISSING]
    for start in range(0, len(missing), 400):
        batch = missing[start:start + 400]
        rows = list(s.scalars(select(model).where(column.in_(batch)).options(*options)))
        found = {getattr(row, column.key): row for row in rows}
        for key in batch:
            projection_put(s, ('row', model), key, found.get(key))
    return {key: projection_get(s, ('row', model), key) for key in wanted}


def prime_projection(s, items):
    """Prime only a visible record set and relationships its summaries need."""
    if projection_enabled(s):
        from projection_batches import prime_projection as prime
        prime(s, items)


def read_response(function):
    """Opt one GET handler in without altering its FastAPI call signature."""
    parameters = signature(function)

    @wraps(function)
    def wrapped(*args, **kwargs):
        s = parameters.bind(*args, **kwargs).arguments['s']
        with read_projection(s):
            return function(*args, **kwargs)

    return wrapped
