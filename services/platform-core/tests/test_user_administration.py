from sqlalchemy import select

from app.models import User
from app.seed import DEMO_PASSWORD


PASSWORD = DEMO_PASSWORD


def login(client, email: str, password: str = PASSWORD):
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=False)


def test_owner_can_onboard_user_with_mandatory_first_password_change(client, db):
    assert login(client, "owner@imperial.local").status_code == 303
    created = client.post(
        "/admin/users",
        data={
            "name": "Valódi Értékesítő",
            "email": "sales.person@example.com",
            "role": "sales",
            "temporary_password": "Temporary-Access-2026!",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    row = db.scalar(select(User).where(User.email == "sales.person@example.com"))
    assert row is not None
    assert row.must_change_password is True
    assert row.active is True

    client.post("/logout")
    first_login = login(client, row.email, "Temporary-Access-2026!")
    assert first_login.status_code == 303
    assert first_login.headers["location"] == "/account/password"
    assert client.get("/", follow_redirects=False).headers["location"] == "/account/password"

    changed = client.post(
        "/account/password",
        data={
            "current_password": "Temporary-Access-2026!",
            "new_password": "Permanent-Access-2026!",
            "confirm_password": "Permanent-Access-2026!",
        },
    )
    assert changed.status_code == 200
    db.refresh(row)
    assert row.must_change_password is False
    assert client.get("/").status_code == 200


def test_non_admin_cannot_manage_users_and_platform_admin_cannot_create_owner(client):
    assert login(client, "marketing@imperial.local").status_code == 303
    assert client.get("/admin/users").status_code == 403
    client.post("/logout")

    assert login(client, "platform-admin@imperial.local").status_code == 303
    denied = client.post(
        "/admin/users",
        data={
            "name": "Tiltott tulajdonos",
            "email": "owner2@example.com",
            "role": "owner",
            "temporary_password": "Temporary-Owner-2026!",
        },
    )
    assert denied.status_code == 403
