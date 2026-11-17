def test_all_module_pages(client):
    for path in ['/intake', '/encoding', '/fields', '/content', '/reconcile', '/runs']:
        response = client.get(path)
        assert response.status_code == 200
        assert "panel" in response.text

def test_all_module_apis_and_idempotent_run(client):
    for path in ['/api/intake/run', '/api/encoding/detect', '/api/fields/normalize', '/api/content/normalize', '/api/reconcile']:
        response = client.post(path, json={})
        assert response.status_code == 200
    first = client.get("/api/runs").json()
    second = client.get("/api/runs").json()
    assert len(first["runs"]) == len(second["runs"]) == 1
    assert first == second
