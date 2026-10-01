import json

import httpx
import pytest

from app import services
from app.config import Settings
from app.whatsapp import CloudApiProvider, SendError, valid_signature


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("012-345 6789", "60123456789"),
        ("+60 12-345 6789", "60123456789"),
        ("0060123456789", "60123456789"),
        ("123456789", "60123456789"),
        ("011-2345 6789", "601123456789"),
        ("abc", None),
        ("123", None),
    ],
)
def test_normalize_phone(raw, expected):
    assert services.normalize_phone(raw) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("TERIMA", "accepted"),
        ("terima kasih, saya terima", "accepted"),
        ("Ya", "accepted"),
        ("ok tuan", "accepted"),
        ("TOLAK", "declined"),
        ("Tak boleh hadir, cuti", "declined"),
        ("saya tidak dapat hadir", "declined"),
        ("siapa ni?", None),
        ("", None),
    ],
)
def test_parse_rsvp(text, expected):
    assert services.parse_rsvp(text) == expected


def test_match_unit():
    assert services.match_unit("bn1") == "Bn 1"
    assert services.match_unit("MK REJ") == "MK Rej"
    assert services.match_unit("Bn. 3") == "Bn 3"
    assert services.match_unit("Bn 9") is None


def test_valid_signature():
    import hashlib
    import hmac

    body = b'{"a":1}'
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert valid_signature("s3cret", body, sig)
    assert not valid_signature("s3cret", body, "sha256=bad")
    assert not valid_signature("s3cret", body, None)
    assert not valid_signature("", body, None)


def _cloud(handler, template=""):
    s = Settings()
    s.whatsapp_token, s.whatsapp_phone_number_id = "tok", "123"
    s.whatsapp_template_name = template
    return CloudApiProvider(s, httpx.Client(transport=httpx.MockTransport(handler)))


PARAMS = {"nama": "Ali", "tajuk": "T", "lokasi": "L", "masa": "M", "pautan": "P", "unit": "Bn 1"}


def test_cloud_provider_text():
    seen = {}

    def handler(req):
        seen["auth"] = req.headers["authorization"]
        seen["json"] = json.loads(req.read())
        return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})

    assert _cloud(handler).send("60123", "hi", PARAMS) == "wamid.1"
    assert seen["auth"] == "Bearer tok"
    assert seen["json"]["type"] == "text" and seen["json"]["to"] == "60123"


def test_cloud_provider_template_and_error():
    p = _cloud(lambda r: httpx.Response(400, json={"error": {"message": "bad number"}}), "panggil")
    body = p.payload("60123", "hi", PARAMS)
    assert body["template"]["name"] == "panggil"
    assert [x["text"] for x in body["template"]["components"][0]["parameters"]] == [
        "Ali",
        "T",
        "L",
        "M",
        "P",
    ]
    with pytest.raises(SendError, match="bad number"):
        p.send("60123", "hi", PARAMS)


def test_cloud_provider_non_json_error():
    p = _cloud(lambda r: httpx.Response(502, text="<html>Bad Gateway</html>"))
    with pytest.raises(SendError, match="HTTP 502"):
        p.send("60123", "hi", PARAMS)
    p = _cloud(lambda r: httpx.Response(200, text="not json"))
    with pytest.raises(SendError):
        p.send("60123", "hi", PARAMS)
