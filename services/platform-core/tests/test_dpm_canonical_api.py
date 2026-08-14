from app.models import ProjectRegistry, User


def test_dpm_reads_live_canonical_project_and_user(client, db):
    project = ProjectRegistry(
        project_id="PRJ-DPM-CANONICAL-001",
        name="DPM kanonikus projekt",
        customer_name="DPM Ugyfel Kft.",
        project_type="design-build",
        status="active",
        risk_level="yellow",
        blocked=False,
        responsible="project-manager@imperial.local",
        next_action="Muszaki utemezes ellenorzese",
    )
    db.add(project)
    db.commit()

    detail = client.get("/api/integrations/dpm/projects/PRJ-DPM-CANONICAL-001")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["project"]["id"] == project.project_id
    assert payload["project"]["riskLevel"] == "yellow"
    assert payload["customer"] == {
        "id": "DPM Ugyfel Kft.",
        "name": "DPM Ugyfel Kft.",
        "source": "project_registry",
    }

    listed = client.get("/api/integrations/dpm/projects?limit=1000")
    assert listed.status_code == 200
    assert project.project_id in {row["id"] for row in listed.json()["projects"]}

    user = db.query(User).filter(User.active.is_(True)).first()
    assert user is not None
    resolved = client.get(f"/api/integrations/dpm/users/{user.email}")
    assert resolved.status_code == 200
    assert resolved.json()["role"] == user.role


def test_dpm_canonical_endpoints_fail_closed_for_unknown_records(client):
    assert client.get("/api/integrations/dpm/projects/UNKNOWN-DPM").status_code == 404
    assert client.get("/api/integrations/dpm/users/missing@example.test").status_code == 404
