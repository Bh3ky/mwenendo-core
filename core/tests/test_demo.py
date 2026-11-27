import pytest


def test_the_demo_page_is_served(client):
    response = client.get("/demo/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    body = response.content.decode()
    assert "reservation playground" in body
    # It calls the real API, with the idempotency header.
    assert "/api/products/" in body
    assert "Idempotency-Key" in body


def test_the_demo_page_has_no_leftover_template_syntax(client):
    body = client.get("/demo/").content.decode()

    # The page is rendered by Django, so a stray {{ or {% in its script would be
    # swallowed or would raise.
    assert "{{" not in body
    assert "{%" not in body


def test_the_demo_page_never_writes_server_text_as_html(client):
    # A reservation's reference is typed by a visitor and shown to others. The page
    # must put server text in with textContent, never innerHTML, or it would be an
    # injection hole.
    body = client.get("/demo/").content.decode()

    assert "innerHTML" not in body
    assert "insertAdjacentHTML" not in body
    assert "document.write" not in body


def test_the_home_page_links_to_the_demo(client):
    assert 'href="/demo/"' in client.get("/").content.decode()


@pytest.mark.django_db
def test_the_demo_page_does_not_need_the_database(client, django_assert_num_queries):
    client.get("/health/")  # load the URL configuration first, outside the count

    with django_assert_num_queries(0):
        client.get("/demo/")
