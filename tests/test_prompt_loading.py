from __future__ import annotations


def test_prompt_activation_changes_active_version(client) -> None:
    before = client.get("/api/prompts").json()
    active_before = [prompt["version"] for prompt in before if prompt["is_active"]]
    assert active_before == ["v1"]

    activate = client.post("/api/prompts/activate", json={"version": "v2"})
    assert activate.status_code == 200
    assert activate.json()["version"] == "v2"

    after = client.get("/api/prompts").json()
    active_after = [prompt["version"] for prompt in after if prompt["is_active"]]
    assert active_after == ["v2"]
