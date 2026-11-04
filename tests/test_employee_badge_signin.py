"""Passwordless printed-badge authentication against isolated local accounts."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from conftest import BADGES, TEST_PIN
from test_admin import edit_employee, employee
from tracking_helpers import ok


ROOT = '/api/admin/employees'
REASON = 'Administrator reviewed replacement of a synthetic employee badge'


def printed_badge(api, monkeypatch, badge):
    """Read the actual QR payload without adding a QR-decoder dependency."""
    links = []
    original = api.application.qrcode.make

    def capture(value, *args, **kwargs):
        links.append(value)
        return original(value, *args, **kwargs)

    with monkeypatch.context() as scope:
        scope.setattr(api.application, 'PUBLIC_BASE_URL', 'https://example.invalid')
        scope.setattr(api.application.qrcode, 'make', capture)
        response = api.get(f'/api/employees/{badge}/qr.png')
    assert response.status_code == 200, response.text
    assert response.headers['content-type'] == 'image/png'
    assert response.headers['cache-control'] == 'no-store'
    assert len(links) == 1
    link = urlsplit(links[0])
    assert parse_qs(link.query) == {'badge': [badge]}
    token = parse_qs(link.fragment)['badge_login'][0]
    assert token not in link.query
    return token, response.content


def change(api, badge, action, **values):
    body = {'action': action, 'expected_version': employee(api, badge)['version'], 'reason': REASON, **values}
    return api.post(f'{ROOT}/{badge}/badge-signin', body)


def test_printed_badge_signs_in_without_pin_and_keeps_identity_and_secret_separate(api, monkeypatch):
    from employee_badge_signin import EmployeeBadgeCredential

    badge = BADGES['welder']
    before = employee(api, badge)
    token, png = printed_badge(api, monkeypatch, badge)
    repeated_token, repeated_png = printed_badge(api, monkeypatch, badge)
    assert (repeated_token, repeated_png) == (token, png)
    assert before['badge_signin'] == {'enabled': True, 'version': 0}
    assert employee(api, badge) == before, 'Printing is read-only'
    with api.session_factory() as session:
        assert session.get(EmployeeBadgeCredential, badge) is None

    with TestClient(api.application.app) as worker:
        response = worker.post('/api/login/badge', json={'token': token})
        logged_in = ok(response)
        assert logged_in['badge'] == badge and logged_in['role'] == 'welder'
        assert 'weld_production' in logged_in['permissions']['capabilities']
        assert ok(worker.get('/api/me')) == logged_in
        cookie = response.headers['set-cookie'].lower()
        assert 'httponly' in cookie and 'samesite=strict' in cookie and 'max-age=28800' in cookie
        assert token not in cookie
        assert token not in response.text
        ok(worker.post('/api/logout'))
        assert worker.get('/api/me').status_code == 401

    rosters = [ok(api.get('/api/employees')), ok(api.get(ROOT)), ok(api.get('/api/employees/directory'))]
    events = ok(api.get('/api/audit'))
    assert any(event['event'] == 'LOGIN' and event['actor'] == badge
               and event['details'] == {'result': 'success', 'method': 'badge'} for event in events)
    assert token not in json.dumps([rosters, events])
    assert 'badge_login=' not in json.dumps([rosters, events])


@pytest.mark.parametrize('kind', ['public_id', 'legacy_link', 'session', 'wrong_key', 'wrong_purpose', 'unsigned', 'unknown_employee'])
def test_only_signed_badge_credentials_authenticate(api, kind):
    from employee_badge_signin import PURPOSE, SIGNING_KEY

    app = api.application
    badge = BADGES['welder']
    claims = {'sub': badge, 'bv': 0, 'p': PURPOSE}
    candidates = {
        'public_id': badge,
        'legacy_link': 'https://example.invalid/?badge=' + badge,
        'session': app.jwt.encode({'sub': badge, 'exp': app.utcnow() + app.dt.timedelta(hours=1)}, app.JWT_SECRET, algorithm='HS256'),
        'wrong_key': app.jwt.encode(claims, 'synthetic-unrelated-signing-key-1234567890', algorithm='HS256'),
        'wrong_purpose': app.jwt.encode({**claims, 'p': 'unrelated-feature'}, SIGNING_KEY, algorithm='HS256'),
        'unsigned': app.jwt.encode(claims, key='', algorithm='none'),
        'unknown_employee': app.jwt.encode({**claims, 'sub': 'NOT-AN-EMPLOYEE'}, SIGNING_KEY, algorithm='HS256'),
    }
    with TestClient(app.app) as worker:
        response = worker.post('/api/login/badge', json={'token': candidates[kind]})
        assert response.status_code == 401
        assert 'fabtrace_session' not in response.cookies
        assert worker.get('/api/me').status_code == 401
        assert candidates[kind] not in response.text


def test_badge_credential_cannot_be_reused_as_session_and_cross_origin_login_is_rejected(api, monkeypatch):
    token, _ = printed_badge(api, monkeypatch, BADGES['handler'])
    with TestClient(api.application.app) as worker:
        worker.cookies.set('fabtrace_session', token)
        assert worker.get('/api/me').status_code == 401
        worker.cookies.clear()
        response = worker.post('/api/login/badge', json={'token': token}, headers={'Origin': 'https://unrelated.invalid'})
        assert response.status_code == 403 and 'fabtrace_session' not in response.cookies
        assert worker.get('/api/me').status_code == 401
        ok(worker.post('/api/login/badge', json={'token': token}, headers={'Origin': 'http://testserver'}))


def test_login_validation_redacts_credential_inputs_and_rate_limit_cannot_be_evaded_with_changed_tokens(api):
    marker = 'SYNTHETIC-SECRET-MUST-NOT-APPEAR'
    with TestClient(api.application.app) as worker:
        for body in ({'token': {'secret': marker}}, {'token': marker * 100}, {'token': marker, 'unexpected': marker}):
            response = worker.post('/api/login/badge', json=body)
            assert response.status_code == 422 and marker not in response.text
            assert all('input' not in row for row in response.json()['detail'])
        for index in range(8):
            response = worker.post('/api/login/badge', json={'token': f'bad-token-{index}'})
            assert response.status_code == 401
        assert worker.post('/api/login/badge', json={'token': 'different-bad-token'}).status_code == 429
        # An ordinary PIN sign-in remains available; the badge bucket is separate.
        ok(worker.post('/api/login', json={'badge': BADGES['welder'], 'pin': TEST_PIN}))


def test_replace_and_disable_revoke_old_prints_and_sessions_with_conflict_protection(api, monkeypatch):
    badge = BADGES['welder']
    original, _ = printed_badge(api, monkeypatch, badge)
    original_version = employee(api, badge)['version']
    with TestClient(api.application.app) as badge_session, TestClient(api.application.app) as pin_session:
        ok(badge_session.post('/api/login/badge', json={'token': original}))
        ok(pin_session.post('/api/login', json={'badge': badge, 'pin': TEST_PIN}))
        replaced = ok(change(api, badge, 'reissue'))
        assert replaced['badge_signin'] == {'enabled': True, 'version': 1}
        assert replaced['version'] == original_version + 1
        assert replaced['reauthenticate'] is False
        assert badge_session.get('/api/me').status_code == 401
        assert pin_session.get('/api/me').status_code == 401
        assert badge_session.post('/api/login/badge', json={'token': original}).status_code == 401
        replacement, _ = printed_badge(api, monkeypatch, badge)
        assert replacement != original
        ok(badge_session.post('/api/login/badge', json={'token': replacement}))
        stale = change(api, badge, 'disable', expected_version=original_version)
        assert stale.status_code == 409
        assert employee(api, badge) == {key: value for key, value in replaced.items() if key != 'reauthenticate'}
        disabled = ok(change(api, badge, 'disable'))
        assert disabled['badge_signin'] == {'enabled': False, 'version': 2}
        assert badge_session.get('/api/me').status_code == 401
        assert badge_session.post('/api/login/badge', json={'token': replacement}).status_code == 401
        with monkeypatch.context() as scope:
            scope.setattr(api.application, 'PUBLIC_BASE_URL', 'https://example.invalid')
            assert api.get(f'/api/employees/{badge}/qr.png').status_code == 409
        assert change(api, badge, 'disable').status_code == 409
        assert employee(api, badge)['version'] == disabled['version']
        ok(pin_session.post('/api/login', json={'badge': badge, 'pin': TEST_PIN}))
        assert ok(pin_session.get('/api/me'))['badge'] == badge

    audit = ok(api.get('/api/audit'))
    changes = [row for row in audit if row['event'] in ('EMPLOYEE_BADGE_REISSUED', 'EMPLOYEE_BADGE_DISABLED')]
    assert len(changes) == 2 and all(row['details']['existing_sessions_revoked'] for row in changes)
    assert original not in json.dumps(audit) and replacement not in json.dumps(audit)


def test_role_and_name_edits_keep_the_badge_but_use_current_permissions(api, monkeypatch):
    badge = BADGES['welder']
    original, image = printed_badge(api, monkeypatch, badge)
    with TestClient(api.application.app) as worker:
        ok(worker.post('/api/login/badge', json={'token': original}))
        edit_employee(api, badge, name='Current painter', role='painter')
        assert worker.get('/api/me').status_code == 401
        assert printed_badge(api, monkeypatch, badge) == (original, image)
        logged_in = ok(worker.post('/api/login/badge', json={'token': original}))
        assert logged_in['name'] == 'Current painter' and logged_in['role'] == 'painter'
        assert 'weld_production' not in logged_in['permissions']['capabilities']


def test_deactivation_and_removal_never_resurrect_previous_badge_credentials(api, monkeypatch):
    badge = BADGES['welder']
    original, _ = printed_badge(api, monkeypatch, badge)
    disabled = edit_employee(api, badge, active=False)
    assert disabled['badge_signin'] == {'enabled': False, 'version': 1}
    assert change(api, badge, 'reissue').status_code == 409
    with TestClient(api.application.app) as worker:
        assert worker.post('/api/login/badge', json={'token': original}).status_code == 401
        enabled = edit_employee(api, badge, active=True)
        assert enabled['badge_signin']['enabled'] is False
        assert worker.post('/api/login/badge', json={'token': original}).status_code == 401
        ok(change(api, badge, 'reissue'))
        current, _ = printed_badge(api, monkeypatch, badge)
        ok(worker.post('/api/login/badge', json={'token': current}))
        removed = ok(api.post(f'{ROOT}/{badge}/remove', {
            'expected_version': employee(api, badge)['version'], 'reason': REASON}))
        assert removed['badge_signin']['enabled'] is False
        assert worker.get('/api/me').status_code == 401
        assert worker.post('/api/login/badge', json={'token': current}).status_code == 401
        assert api.post(f'{ROOT}/{badge}/badge-signin', {
            'expected_version': removed['version'], 'reason': REASON, 'action': 'reissue'}).status_code == 409
        ok(api.post(f'{ROOT}/{badge}/restore', {'expected_version': removed['version'], 'reason': REASON}))
        restored = edit_employee(api, badge, active=True)
        assert restored['badge_signin']['enabled'] is False
        assert worker.post('/api/login/badge', json={'token': current}).status_code == 401


@pytest.mark.parametrize('role', [None, 'handler', 'supervisor', 'inspector'])
def test_only_administrators_can_print_or_manage_signin_badges(api, monkeypatch, role):
    badge = BADGES['welder']
    before = employee(api, badge)
    expected = 401 if role is None else 403
    monkeypatch.setattr(api.application, 'PUBLIC_BASE_URL', 'https://example.invalid')
    assert api.get(f'/api/employees/{badge}/qr.png', role=role).status_code == expected
    for action in ('reissue', 'disable'):
        assert api.post(f'{ROOT}/{badge}/badge-signin', {
            'action': action, 'expected_version': before['version'], 'reason': REASON}, role=role).status_code == expected
    assert employee(api, badge) == before


def test_reissuing_own_admin_badge_requires_reauthentication_but_pin_fallback_works(api, monkeypatch):
    badge = BADGES['admin']
    token, _ = printed_badge(api, monkeypatch, badge)
    version = employee(api, badge)['version']
    with TestClient(api.application.app) as admin:
        ok(admin.post('/api/login/badge', json={'token': token}))
        result = ok(admin.post(f'{ROOT}/{badge}/badge-signin', json={
            'expected_version': version, 'action': 'reissue', 'reason': REASON}))
        assert result['reauthenticate'] is True
        assert admin.get('/api/me').status_code == 401
        assert admin.post('/api/login/badge', json={'token': token}).status_code == 401
        ok(admin.post('/api/login', json={'badge': badge, 'pin': TEST_PIN}))
        assert ok(admin.get('/api/me'))['role'] == 'admin'


@pytest.mark.parametrize('change_kind, expected_status', [('demoted_admin', 403), ('revoked_admin', 401), ('disabled_employee', 404)])
def test_queued_badge_print_rechecks_admin_and_employee_before_exposing_a_credential(api, monkeypatch, change_kind, expected_status):
    import flow
    from administration import EmployeeAccessState

    original_lock = flow.lock_topology

    def change_while_waiting(session):
        # Simulate a committed access edit after the initial authentication but
        # before the request acquires its shared administrative lock.
        with api.session_factory() as other:
            if change_kind == 'demoted_admin':
                other.get(api.application.Employee, BADGES['admin']).role = 'handler'
            elif change_kind == 'revoked_admin':
                other.add(EmployeeAccessState(badge=BADGES['admin'], version=1, session_version=1,
                    updated_by=BADGES['admin'], updated_at=api.application.utcnow()))
            else:
                other.get(api.application.Employee, BADGES['welder']).active = False
            other.commit()
        return original_lock(session)

    def no_image(*args, **kwargs):
        pytest.fail('A revoked or unauthorized badge request generated a credential image')

    monkeypatch.setattr(flow, 'lock_topology', change_while_waiting)
    monkeypatch.setattr(api.application, 'PUBLIC_BASE_URL', 'https://example.invalid')
    monkeypatch.setattr(api.application.qrcode, 'make', no_image)
    response = api.get(f'/api/employees/{BADGES["welder"]}/qr.png')
    assert response.status_code == expected_status, response.text
