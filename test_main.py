import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test-products.db")

    with TestClient(main.app) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "1.1.0"
    }


def test_get_products(client):
    response = client.get("/products")

    assert response.status_code == 200
    assert response.json() == {"products": []}


def test_get_product(client):
    created = client.post(
        "/products",
        json={"name": "Laptop", "price": 500}
    ).json()

    response = client.get(f"/products/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_product_not_found(client):
    response = client.get("/products/999999")

    assert response.status_code == 404


def test_create_product(client):
    response = client.post(
        "/products",
        json={"name": "Keyboard", "price": 25}
    )

    assert response.status_code == 201
    product = response.json()

    assert product["name"] == "Keyboard"
    assert product["price"] == 25

    saved = client.get(f"/products/{product['id']}")
    assert saved.json() == product


def test_reject_invalid_price(client):
    response = client.post(
        "/products",
        json={"name": "Keyboard", "price": -10}
    )

    assert response.status_code == 422


def test_product_persists_across_clients(client):
    created = client.post(
        "/products",
        json={"name": "Monitor", "price": 150}
    ).json()

    with TestClient(main.app) as another_client:
        response = another_client.get(f"/products/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created