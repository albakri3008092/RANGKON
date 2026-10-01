import io

from openpyxl import Workbook

from app import main
from app.db import SessionLocal
from app.models import Invitation


def test_requires_login(client):
    assert client.get("/members", follow_redirects=False).status_code == 303
    assert client.get("/api/events/1/dashboard").status_code == 401
    r = client.post("/login", data={"password": "salah"})
    assert "Kata laluan salah" in r.text


def _member(admin, name, phone, unit):
    return admin.post("/members", data={"name": name, "phone": phone, "unit": unit, "rank": "Kpl"})


def _event(admin):
    r = admin.post(
        "/events",
        data={
            "title": "Perhimpunan",
            "location": "Padang",
            "starts_at": "2020-01-01T08:00",
            "message": "Salam {nama} ({unit}) {tajuk} {pautan}",
        },
    )
    return int(str(r.url).rstrip("/").split("/")[-1])


def test_member_add_edit_import(admin):
    _member(admin, "Ali", "012-3456789", "MK Rej")
    r = admin.get("/members")
    assert "Ali" in r.text and "+60123456789" in r.text
    assert "sudah didaftarkan" in _member(admin, "Dup", "0123456789", "Bn 1").text

    r = admin.post("/members/1", data={"name": "Ali Baru", "phone": "0123456789", "unit": "Bn 2"})
    assert "Ali Baru dikemas kini" in r.text

    csv = "nama,telefon,unit\nAbu,013-1111111,bn1\nTiada,,Bn 1\nAli Lagi,0123456789,Bn 3\n"
    r = admin.post("/members/import", files={"file": ("a.csv", csv, "text/csv")})
    assert "1 baru, 1 dikemas kini, 1 dilangkau" in r.text

    wb = Workbook()
    wb.active.append(["Nama", "No Telefon", "Pangkat"])
    wb.active.append(["Siti", "0145556666", "Prebet"])
    buf = io.BytesIO()
    wb.save(buf)
    r = admin.post(
        "/members/import",
        data={"unit": "Bn 2"},
        files={"file": ("a.xlsx", buf.getvalue(), "application/octet-stream")},
    )
    assert "1 baru" in r.text
    assert "Siti" in admin.get("/members?unit=Bn 2").text


def test_full_flow_by_unit(admin):
    _member(admin, "Ali", "0123456789", "MK Rej")
    _member(admin, "Abu", "0131111111", "Bn 1")
    _member(admin, "Chong", "0142222222", "Bn 2")
    event_id = _event(admin)

    main.provider.outbox.clear()
    r = admin.post(f"/events/{event_id}/send", data={"target_units": ["MK Rej", "Bn 1"]})
    assert "2 mesej WhatsApp" in r.text
    assert sorted(m["to"] for m in main.provider.outbox) == ["60123456789", "60131111111"]
    assert "https://rangkon.test/c/" in main.provider.outbox[0]["body"]
    assert (
        "(MK Rej)" in main.provider.outbox[0]["body"] or "(Bn 1)" in main.provider.outbox[0]["body"]
    )

    r = admin.post(f"/events/{event_id}/send", data={"target_units": ["MK Rej", "Bn 1"]})
    assert "Tiada ahli baru" in r.text

    d = admin.get(f"/api/events/{event_id}/dashboard").json()
    assert d["overall"]["total"] == 2 and d["overall"]["sent"] == 2
    assert d["overall"]["accepted"] == 0 and d["overall"]["no_response"] == 2
    assert d["units"]["Bn 2"]["total"] == 0

    with SessionLocal() as db:
        ali = db.query(Invitation).join(Invitation.member).filter_by(name="Ali").one()
        abu = db.query(Invitation).join(Invitation.member).filter_by(name="Abu").one()

    # WhatsApp read status alone does not count as accepted
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {
                                    "id": ali.wa_message_id,
                                    "status": "delivered",
                                    "timestamp": "1700000000",
                                },
                                {
                                    "id": ali.wa_message_id,
                                    "status": "read",
                                    "timestamp": "1700000100",
                                },
                                {
                                    "id": abu.wa_message_id,
                                    "status": "read",
                                    "timestamp": "1700000100",
                                },
                                {
                                    "id": abu.wa_message_id,
                                    "status": "delivered",
                                    "timestamp": "1700000200",
                                },
                            ]
                        }
                    }
                ]
            }
        ]
    }
    assert admin.post("/webhook/whatsapp", json=payload).json()["statuses"] == 4
    d = admin.get(f"/api/events/{event_id}/dashboard").json()
    assert d["overall"]["read"] == 2 and d["overall"]["accepted"] == 0

    reply = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "60123456789",
                                    "timestamp": "1700000300",
                                    "type": "text",
                                    "text": {"body": "Terima tuan"},
                                },
                            ]
                        }
                    }
                ]
            }
        ]
    }
    assert admin.post("/webhook/whatsapp", json=reply).json()["replies"] == 1

    r = admin.post(f"/c/{abu.token}/rsvp", data={"answer": "declined"})
    assert "TOLAK" in r.text

    d = admin.get(f"/api/events/{event_id}/dashboard").json()
    assert d["units"]["MK Rej"]["accepted"] == 1
    assert d["units"]["Bn 1"]["declined"] == 1
    row = next(r for r in d["rows"] if r["name"] == "Ali")
    assert row["rsvp"] == "accepted" and row["rsvp_via"] == "whatsapp"

    # check-in via link (event start in the past, so window is open)
    r = admin.post(f"/c/{ali.token}/checkin")
    assert "Kehadiran anda telah direkod" in r.text
    r = admin.post(f"/events/{event_id}/kiosk", data={"phone": "013-1111111"})
    assert "Hadir:" in r.text
    r = admin.post(f"/events/{event_id}/kiosk", data={"phone": "0199999999"})
    assert "Tiada panggilan" in r.text

    d = admin.get(f"/api/events/{event_id}/dashboard").json()
    assert d["overall"]["attended"] == 2
    assert d["units"]["MK Rej"]["attended"] == 1 and d["units"]["Bn 1"]["attended"] == 1

    csv = admin.get(f"/events/{event_id}/export.csv").text
    assert "Terima" in csv and "Tolak" in csv

    page = admin.get(f"/events/{event_id}")
    assert page.status_code == 200 and "Mengikut unit" in page.text


def test_simulate_and_admin_override(admin):
    _member(admin, "Ali", "0123456789", "Bn 3")
    event_id = _event(admin)
    admin.post(f"/events/{event_id}/send", data={"target_units": ["Bn 3"]})
    with SessionLocal() as db:
        inv = db.query(Invitation).one()
    assert (
        admin.post(f"/api/invitations/{inv.id}/simulate", data={"action": "read"}).status_code
        == 200
    )
    assert (
        admin.post(f"/api/invitations/{inv.id}/simulate", data={"action": "TERIMA"}).status_code
        == 200
    )
    d = admin.get(f"/api/events/{event_id}/dashboard").json()
    assert d["units"]["Bn 3"]["accepted"] == 1 and d["units"]["Bn 3"]["read"] == 1

    admin.post(f"/api/invitations/{inv.id}/rsvp", data={"answer": "clear"})
    admin.post(f"/api/invitations/{inv.id}/attend")
    d = admin.get(f"/api/events/{event_id}/dashboard").json()
    assert d["overall"]["accepted"] == 0 and d["overall"]["attended"] == 1


def test_webhook_verify_and_signature(client, monkeypatch):
    monkeypatch.setattr(main.settings, "whatsapp_verify_token", "vt")
    r = client.get(
        "/webhook/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "42"},
    )
    assert r.text == "42"
    r = client.get("/webhook/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "x"})
    assert r.status_code == 403
    monkeypatch.setattr(main.settings, "whatsapp_app_secret", "s")
    assert client.post("/webhook/whatsapp", json={}).status_code == 403


def _reply(phone, text, ts):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [{"from": phone, "timestamp": ts, "text": {"body": text}}]
                        }
                    }
                ]
            }
        ]
    }


def test_invitation_keeps_unit_phone_and_history(admin):
    _member(admin, "Ali", "0123456789", "Bn 1")
    event_id = _event(admin)
    admin.post(f"/events/{event_id}/send", data={"target_units": ["Bn 1"]})
    with SessionLocal() as db:
        inv = db.query(Invitation).one()
        token, member_id = inv.token, inv.member_id
    admin.get(f"/c/{token}")
    d = admin.get(f"/api/events/{event_id}/dashboard").json()
    assert d["rows"][0]["status"] == "sent"

    admin.post(f"/members/{member_id}", data={"name": "Ali", "phone": "0131111111", "unit": "Bn 2"})
    admin.post("/webhook/whatsapp", json=_reply("60123456789", "TERIMA", "1700000600"))
    admin.post("/webhook/whatsapp", json=_reply("60123456789", "TOLAK", "1700000000"))
    d = admin.get(f"/api/events/{event_id}/dashboard").json()
    assert d["units"]["Bn 1"]["accepted"] == 1 and d["units"]["Bn 2"]["total"] == 0
    assert d["rows"][0]["phone"] == "60123456789"

    r = admin.post(f"/members/{member_id}/delete")
    assert "dinyahaktifkan" in r.text
    assert admin.get(f"/api/events/{event_id}/dashboard").json()["overall"]["total"] == 1


def test_cloud_webhook_requires_signature(client, monkeypatch):
    monkeypatch.setattr(main.settings, "whatsapp_provider", "cloud")
    assert client.post("/webhook/whatsapp", json={}).status_code == 403


def test_cross_origin_post_rejected(admin):
    r = admin.post("/members/1/delete", headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    r = admin.post("/members/1/delete", headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403
    r = admin.post(
        "/members/1/delete",
        headers={"sec-fetch-site": "same-origin", "origin": "https://proxy.example"},
    )
    assert r.status_code == 200


def test_group_link_flow(admin):
    admin.post(
        "/members",
        data={"name": "Ali", "phone": "0123456789", "unit": "Bn 1", "service_no": "T 1001"},
    )
    _member(admin, "Abu", "0131111111", "Bn 2")
    _member(admin, "Siti", "0142222222", "MK Rej")
    event_id = _event(admin)
    r = admin.post(f"/events/{event_id}/share", data={"target_units": ["Bn 1", "Bn 2"]})
    assert "2 ahli" in r.text and "https://wa.me/?text=" in r.text
    with SessionLocal() as db:
        code = db.get(main.Event, event_id).public_code
    assert f"https://rangkon.test/p/{code}" in r.text

    page = admin.get(f"/p/{code}")
    assert page.status_code == 200 and "no. tentera" in page.text
    r = admin.post(f"/p/{code}", data={"ident": "t1001"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/c/")
    admin.post(r.headers["location"] + "/rsvp", data={"answer": "accepted"})
    r = admin.post(f"/p/{code}", data={"ident": "013-1111111"}, follow_redirects=False)
    admin.post(r.headers["location"] + "/rsvp", data={"answer": "declined"})
    for ident in ("0142222222", "0199999999", " "):
        assert "tiada dalam senarai" in admin.post(f"/p/{code}", data={"ident": ident}).text

    d = admin.get(f"/api/events/{event_id}/dashboard").json()
    assert d["units"]["Bn 1"]["accepted"] == 1 and d["units"]["Bn 2"]["declined"] == 1
    assert d["units"]["MK Rej"]["total"] == 0
    assert d["overall"]["group"] == 2 and d["overall"]["sent"] == 0
    assert admin.post(f"/events/{event_id}/share", data={"target_units": ["Bn 1"]}).status_code
    assert admin.get(f"/api/events/{event_id}/dashboard").json()["overall"]["total"] == 2
