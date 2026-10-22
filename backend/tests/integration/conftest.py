import pytest


@pytest.fixture(autouse=True)
def _clean_db(db):
    """Mọi test integration chạy trên DB sạch."""
    return db
