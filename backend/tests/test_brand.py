from app.main import create_app


def test_public_api_identity():
    assert create_app().title == "Intervella API"
