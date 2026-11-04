"""Revocable sign-in credentials for printed employee badges.

The permanent employee ID remains public identity, not authentication. Only a
server-signed credential printed by an administrator can start a session. The
credential lives in the QR URL fragment so ordinary requests/referrers do not
carry it; the sign-in page sends it in a POST body.
"""

import hashlib
import hmac
import time
from typing import Literal
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, select
from sqlalchemy.orm import Session

from main import (Base, Employee, JWT_SECRET, audit, auth, db, failed,
                  finish_login, phone_link, utcnow)
from administration import (ReasonIn, _commit, _employee_dict, _locked_employee,
                            _update_access, employee_is_removed)


router = APIRouter(tags=['employee badge sign-in'])
PURPOSE = 'badge-login-v1'
# Domain separation prevents a badge credential from being accepted as an
# ordinary session cookie or as a token used by any other existing feature.
SIGNING_KEY = hmac.new(JWT_SECRET.encode(), b'fabtrace:employee-badge-login:v1', hashlib.sha256).digest()
INVALID_BADGE = 'Badge sign-in is unavailable. Ask an administrator to print or replace your sign-in badge.'


class EmployeeBadgeCredential(Base):
    __tablename__ = 'employee_badge_credentials'
    __table_args__ = (CheckConstraint('version >= 1', name='ck_employee_badge_credential_version'),)
    badge = Column(String(80), ForeignKey('employees.badge'), primary_key=True)
    version = Column(Integer, nullable=False)
    enabled = Column(Boolean, nullable=False)
    updated_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


def _credential(s, badge):
    return s.scalar(select(EmployeeBadgeCredential).where(EmployeeBadgeCredential.badge == badge)
        .execution_options(populate_existing=True))


def badge_signin_status(s, badge):
    """Only nonsecret state is suitable for rosters, history and exports.

    Version zero needs no migration or issuance write. An active employee can
    use it only after an administrator prints its signed QR. Old public-ID
    badges contain no signature and cannot authenticate.
    """
    state = _credential(s, badge)
    return {'enabled': bool(state.enabled) if state else True,
            'version': state.version if state else 0}


def employee_badge_link(s, employee):
    state = badge_signin_status(s, employee.badge)
    if not state['enabled']:
        raise HTTPException(409, 'Badge sign-in is disabled. Reissue this employee\'s badge before printing it.')
    token = jwt.encode({'sub': employee.badge, 'bv': state['version'], 'p': PURPOSE},
                       SIGNING_KEY, algorithm='HS256')
    return phone_link('badge', employee.badge) + '#' + urlencode({'badge_login': token})


def invalidate_badge(s, employee, actor, *, enabled=False):
    """Caller holds the normal administrative/employee locks.

    The credential stores no bearer secret. Incrementing its public version
    invalidates every earlier print, including after later account reactivation.
    """
    state = _credential(s, employee.badge)
    if state is None:
        state = EmployeeBadgeCredential(badge=employee.badge, version=0)
        s.add(state)
    state.version += 1
    state.enabled = enabled
    state.updated_by, state.updated_at = actor.badge, utcnow()
    return state


class BadgeLoginIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(min_length=1, max_length=1024, strict=True)


class BadgeSigninChangeIn(ReasonIn):
    expected_version: int = Field(ge=0, strict=True)
    action: Literal['reissue', 'disable']


@router.post('/api/login/badge')
def badge_login(data: BadgeLoginIn, response: Response, request: Request, s: Session = Depends(db)):
    # One bucket per client, not per untrusted token or claimed badge. Changing
    # an invalid token must not evade the existing eight-attempt/15-minute rule.
    key = 'badge-login:' + (request.client.host if request.client else 'unknown')
    failed[key] = [at for at in failed.get(key, []) if time.time() - at < 900]
    if len(failed[key]) >= 8:
        raise HTTPException(429, 'Too many attempts; try again later')
    try:
        payload = jwt.decode(data.token, SIGNING_KEY, algorithms=['HS256'],
            options={'require': ['sub', 'bv', 'p']})
        badge, version = payload['sub'], payload['bv']
        if (payload['p'] != PURPOSE or not isinstance(badge, str) or not 1 <= len(badge) <= 80
                or type(version) is not int or version < 0):
            raise jwt.InvalidTokenError()
    except jwt.InvalidTokenError:
        failed[key].append(time.time())
        raise HTTPException(401, INVALID_BADGE) from None

    employee = s.scalar(select(Employee).where(Employee.badge == badge).with_for_update()
        .execution_options(populate_existing=True))
    state = badge_signin_status(s, badge)
    if (not employee or not employee.active or employee_is_removed(s, badge)
            or not state['enabled'] or state['version'] != version):
        failed[key].append(time.time())
        raise HTTPException(401, INVALID_BADGE)
    failed.pop(key, None)
    return finish_login(s, employee, response, method='badge')


@router.post('/api/admin/employees/{badge}/badge-signin')
def change_badge_signin(badge: str, data: BadgeSigninChangeIn,
                       u: Employee = Depends(auth), s: Session = Depends(db)):
    employee, access, actor = _locked_employee(s, badge, u, data.expected_version)
    if employee_is_removed(s, badge):
        raise HTTPException(409, 'Restore this removed employee before changing badge sign-in.')
    if data.action == 'reissue' and not employee.active:
        raise HTTPException(409, 'Activate this employee before reissuing a sign-in badge.')
    before = badge_signin_status(s, badge)
    if data.action == 'disable' and not before['enabled']:
        raise HTTPException(409, 'Badge sign-in is already disabled for this employee.')
    invalidate_badge(s, employee, actor, enabled=data.action == 'reissue')
    _update_access(s, employee, access, actor, utcnow(), True)
    s.flush()
    after = _employee_dict(s, employee)
    audit(s, None, actor.badge,
        'EMPLOYEE_BADGE_REISSUED' if data.action == 'reissue' else 'EMPLOYEE_BADGE_DISABLED',
        {'badge': badge, 'reason': data.reason, 'from': before, 'to': after['badge_signin'],
         'existing_sessions_revoked': True})
    _commit(s)
    return {**after, 'reauthenticate': actor.badge == employee.badge}
