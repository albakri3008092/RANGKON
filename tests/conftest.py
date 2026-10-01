import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["RANGKON_ADMIN_PASSWORD"] = "rahsia"
os.environ["RANGKON_WHATSAPP_PROVIDER"] = "simulate"
os.environ["RANGKON_PUBLIC_BASE_URL"] = "https://rangkon.test"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def admin(client):
    r = client.post("/login", data={"password": "rahsia", "next": "/events"})
    assert r.status_code == 200
    return client
