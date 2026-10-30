import pytest

from webhook_service import create_app, db


class FakeClock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def client(db_path):
    app = create_app(db_path)
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def conn(db_path):
    db.init_db(db_path)
    connection = db.connect(db_path)
    yield connection
    connection.close()


@pytest.fixture
def clock():
    return FakeClock()
