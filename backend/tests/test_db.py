from app.db import normalize_database_url


def test_normalize_database_url_adds_asyncpg_driver_to_postgresql_scheme():
    url = "postgresql://user:pass@host:5432/dbname"
    assert normalize_database_url(url) == "postgresql+asyncpg://user:pass@host:5432/dbname"


def test_normalize_database_url_adds_asyncpg_driver_to_postgres_scheme():
    url = "postgres://user:pass@host:5432/dbname"
    assert normalize_database_url(url) == "postgresql+asyncpg://user:pass@host:5432/dbname"


def test_normalize_database_url_leaves_explicit_driver_alone():
    url = "postgresql+asyncpg://user:pass@host:5432/dbname"
    assert normalize_database_url(url) == url
