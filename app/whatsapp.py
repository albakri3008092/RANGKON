import hashlib
import hmac
import uuid
from typing import Protocol

import httpx

from .config import Settings

TEMPLATE_PARAM_ORDER = ["nama", "tajuk", "lokasi", "masa", "pautan"]


class SendError(Exception):
    pass


class Provider(Protocol):
    name: str

    def send(self, phone: str, body: str, params: dict[str, str]) -> str: ...


class SimulatedProvider:
    """Does not contact WhatsApp; records messages so the flow can be tried end to end."""

    name = "simulate"

    def __init__(self) -> None:
        self.outbox: list[dict[str, str]] = []

    def send(self, phone: str, body: str, params: dict[str, str]) -> str:
        msg_id = f"sim.{uuid.uuid4().hex}"
        self.outbox.append({"id": msg_id, "to": phone, "body": body})
        return msg_id


class CloudApiProvider:
    """WhatsApp Business Cloud API (graph.facebook.com/<ver>/<phone_number_id>/messages)."""

    name = "cloud"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        if not settings.whatsapp_token or not settings.whatsapp_phone_number_id:
            raise ValueError("WHATSAPP_TOKEN dan WHATSAPP_PHONE_NUMBER_ID mesti ditetapkan")
        self.settings = settings
        self.url = (
            f"https://graph.facebook.com/{settings.whatsapp_api_version}/"
            f"{settings.whatsapp_phone_number_id}/messages"
        )
        self.client = client or httpx.Client(timeout=20)

    def payload(self, phone: str, body: str, params: dict[str, str]) -> dict:
        s = self.settings
        if s.whatsapp_template_name:
            return {
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "template",
                "template": {
                    "name": s.whatsapp_template_name,
                    "language": {"code": s.whatsapp_template_lang},
                    "components": [
                        {
                            "type": "body",
                            "parameters": [
                                {"type": "text", "text": params[k]} for k in TEMPLATE_PARAM_ORDER
                            ],
                        }
                    ],
                },
            }
        return {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {"body": body, "preview_url": True},
        }

    def send(self, phone: str, body: str, params: dict[str, str]) -> str:
        try:
            resp = self.client.post(
                self.url,
                headers={"Authorization": f"Bearer {self.settings.whatsapp_token}"},
                json=self.payload(phone, body, params),
            )
        except httpx.HTTPError as exc:
            raise SendError(f"Ralat rangkaian: {exc}") from exc
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            err = data.get("error", {})
            raise SendError(err.get("message") or f"HTTP {resp.status_code}")
        try:
            return data["messages"][0]["id"]
        except (KeyError, IndexError) as exc:
            raise SendError("Respons WhatsApp tiada message id") from exc


def build_provider(settings: Settings) -> Provider:
    if settings.whatsapp_provider == "cloud":
        return CloudApiProvider(settings)
    return SimulatedProvider()


def valid_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    if not app_secret:
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))
