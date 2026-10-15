from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "1.0.1"
    }


def test_get_products():
    response = client.get("/products")

    assert response.status_code == 200
    assert isinstance(response.json()["products"], list)


def test_get_product():
    response = client.get("/products/1")

    assert response.status_code == 200
    assert response.json()["id"] == 1


def test_product_not_found():
    response = client.get("/products/999999")

    assert response.status_code == 404


def test_create_product():
    response = client.post(
        "/products",
        json={"name": "Keyboard", "price": 25}
    )

    assert response.status_code == 201

    product = response.json()
    assert product["name"] == "Keyboard"
    assert product["price"] == 25

    saved = client.get(f"/products/{product['id']}")

    assert saved.status_code == 200
    assert saved.json() == product


def test_reject_invalid_price():
    response = client.post(
        "/products",
        json={"name": "Keyboard", "price": -10}
    )

    assert response.status_code == 422