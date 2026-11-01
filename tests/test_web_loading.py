"""Public asset reuse must never make authenticated records or HTML stale."""
import re


def test_release_assets_cache_but_records_and_shell_do_not(api, application):
    version = application.APP_VERSION
    for path in ('/static/tracking.js', '/static/orders.css'):
        asset = api.get(path + '?v=' + version, role=None)
        assert asset.status_code == 200
        assert asset.headers['cache-control'] == 'public, max-age=86400'
        assert asset.headers['x-content-type-options'] == 'nosniff'
        for suffix in ('', '?v=old-release'):
            assert api.get(path + suffix, role=None).headers['cache-control'] == 'no-store'
    for path in ('/', '/api/me', '/api/items?limit=1'):
        response = api.get(path)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
    missing = api.get('/static/missing.js?v=' + version, role=None)
    assert missing.status_code == 404
    assert missing.headers['cache-control'] == 'no-store'


def test_shell_changes_asset_urls_with_each_release(api, application):
    html = api.get('/', role=None).text
    versions = re.findall(r'/static/[^\s"\'<>?]+\.(?:js|css)\?v=([^\s"\'<>]+)', html)
    assert len(versions) > 20
    assert set(versions) == {application.APP_VERSION}
    assert '<script src="https://unpkg.com/html5-qrcode' not in html
