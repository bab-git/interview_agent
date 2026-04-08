from __future__ import annotations


def test_prompt_version_can_be_activated_when_local_admin_mode_is_enabled(client) -> None:
    before = client.get("/api/prompts").json()
    active_before = [prompt["version"] for prompt in before if prompt["is_active"]]
    assert active_before == ["v1"]

    activate = client.post("/api/prompts/activate", json={"version": "v2"})
    assert activate.status_code == 200
    assert activate.json()["version"] == "v2"

    after = client.get("/api/prompts").json()
    active_after = [prompt["version"] for prompt in after if prompt["is_active"]]
    assert active_after == ["v2"]


def test_prompt_mutation_is_blocked_in_public_demo_mode(locked_prompt_client) -> None:
    activate = locked_prompt_client.post("/api/prompts/activate", json={"version": "v2"})
    assert activate.status_code == 403
    assert "disabled by default" in activate.json()["detail"]
