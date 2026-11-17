import pytest
from django.db import connection


def test_health_check_returns_healthy(client):
    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.django_db
def test_tests_run_against_a_separate_database():
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        (name,) = cursor.fetchone()

    assert name.startswith("test_")
