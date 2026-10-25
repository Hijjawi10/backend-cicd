import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test-products.db")

    with TestClient(main.app) as test_client:
        yield test_client


def create_product(client, **overrides):
    payload = {
        "name": "Keyboard",
        "price": 25,
        "stock": 0,
    }
    payload.update(overrides)

    response = client.post("/products", json=payload)

    assert response.status_code == 201, response.text
    return response.json()


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "1.1.0",
    }


def test_get_products(client):
    response = client.get("/products")

    assert response.status_code == 200
    assert response.json() == {"products": []}


def test_get_product(client):
    product = create_product(client, name="Laptop", price=500)

    response = client.get(f"/products/{product['id']}")

    assert response.status_code == 200
    assert response.json() == product


def test_product_not_found(client):
    response = client.get("/products/999999")

    assert response.status_code == 404


def test_create_product(client):
    product = create_product(client)

    assert product["name"] == "Keyboard"
    assert product["price"] == 25
    assert product["stock"] == 0

    saved = client.get(f"/products/{product['id']}")

    assert saved.status_code == 200
    assert saved.json() == product


def test_reject_invalid_price(client):
    response = client.post(
        "/products",
        json={"name": "Keyboard", "price": -10},
    )

    assert response.status_code == 422


def test_product_persists_across_clients(client):
    product = create_product(client, name="Monitor", price=150)

    with TestClient(main.app) as another_client:
        response = another_client.get(f"/products/{product['id']}")

    assert response.status_code == 200
    assert response.json() == product


def test_get_products_by_name(client):
    first = create_product(client, name="Keyboard", price=25)
    second = create_product(client, name="Keyboard", price=40)
    create_product(client, name="Mouse", price=10)

    response = client.get("/get_products_by_name/Keyboard")

    assert response.status_code == 200
    products = response.json()["products"]
    assert {p["id"] for p in products} == {
        first["id"],
        second["id"],
    }


def test_name_not_found(client):
    response = client.get("/get_products_by_name/Unknown")

    assert response.status_code == 404


def test_get_products_by_price(client):
    first = create_product(client, name="Keyboard", price=25)
    second = create_product(client, name="Mouse", price=25)
    create_product(client, name="Monitor", price=150)

    response = client.get("/get_products_by_price/25")

    assert response.status_code == 200
    products = response.json()["products"]
    assert {p["id"] for p in products} == {
        first["id"],
        second["id"],
    }


def test_price_not_found(client):
    response = client.get("/get_products_by_price/999")

    assert response.status_code == 404


def test_price_must_be_number(client):
    response = client.get("/get_products_by_price/abc")

    assert response.status_code == 422


def test_delete_product(client):
    product = create_product(client)

    response = client.delete(f"/products/{product['id']}")

    assert response.status_code == 204
    assert response.content == b""

    check = client.get(f"/products/{product['id']}")
    assert check.status_code == 404


def test_delete_product_not_found(client):
    response = client.delete("/products/999999")

    assert response.status_code == 404


def test_patch_product_preserves_other_fields(client):
    product = create_product(
        client,
        category="Electronics",
        stock=10,
    )

    response = client.patch(
        f"/products/{product['id']}",
        json={"price": 30},
    )

    assert response.status_code == 200
    assert response.json() == {**product, "price": 30}

    saved = client.get(f"/products/{product['id']}")
    assert saved.json() == response.json()


def test_reject_empty_or_null_patch(client):
    product = create_product(client, name="Mouse", price=10)
    url = f"/products/{product['id']}"

    assert client.patch(url, json={}).status_code == 422
    assert client.patch(url, json={"name": None}).status_code == 422
    assert client.get(url).json() == product


def test_low_stock(client):
    low = create_product(
        client,
        name="Mouse",
        price=10,
        stock=2,
    )

    create_product(client, stock=5)

    response = client.get("/products/low-stock?threshold=5")

    assert response.status_code == 200
    assert response.json()["products"] == [low]


def test_categories_and_category_report(client):
    create_product(
        client,
        name="Keyboard",
        price=25,
        stock=2,
        category="Electronics",
    )
    create_product(
        client,
        name="Mouse",
        price=10,
        stock=3,
        category="Electronics",
    )
    create_product(
        client,
        name="Chair",
        price=100,
        stock=1,
        category="Furniture",
    )

    categories = client.get("/categories")

    assert categories.status_code == 200
    assert categories.json() == {
        "categories": ["Electronics", "Furniture"],
    }

    response = client.get("/reports/categories")

    assert response.status_code == 200
    assert response.json()["categories"] == [
        {
            "category": "Electronics",
            "total_products": 2,
            "total_stock": 5,
            "inventory_value": 80,
        },
        {
            "category": "Furniture",
            "total_products": 1,
            "total_stock": 1,
            "inventory_value": 100,
        },
    ]


def test_increase_stock_creates_adjustment(client):
    product = create_product(client, stock=5)

    response = client.post(
        f"/inventory/products/{product['id']}/adjustments",
        json={
            "quantity_change": 10,
            "reason": "New delivery",
        },
    )

    assert response.status_code == 201, response.text

    data = response.json()
    assert data["product"]["stock"] == 15

    movement = data["adjustment"]
    assert movement["product_id"] == product["id"]
    assert movement["product_name"] == "Keyboard"
    assert movement["previous_stock"] == 5
    assert movement["quantity_change"] == 10
    assert movement["new_stock"] == 15
    assert movement["reason"] == "New delivery"
    assert movement["created_at"].endswith("Z")

    saved = client.get(f"/products/{product['id']}")
    assert saved.status_code == 200
    assert saved.json()["stock"] == 15

    history = client.get(
        "/inventory/adjustments",
        params={"product_id": product["id"]},
    )

    assert history.status_code == 200
    assert history.json()["adjustments"] == [movement]


def test_decrease_stock_to_zero(client):
    product = create_product(
        client,
        name="Mouse",
        price=10,
        stock=3,
    )

    response = client.post(
        f"/inventory/products/{product['id']}/adjustments",
        json={
            "quantity_change": -3,
            "reason": "Sold three items",
        },
    )

    assert response.status_code == 201, response.text

    data = response.json()
    assert data["product"]["stock"] == 0
    assert data["adjustment"]["previous_stock"] == 3
    assert data["adjustment"]["quantity_change"] == -3
    assert data["adjustment"]["new_stock"] == 0

    saved = client.get(f"/products/{product['id']}")
    assert saved.json()["stock"] == 0


def test_insufficient_stock_changes_nothing(client):
    product = create_product(
        client,
        name="Monitor",
        price=150,
        stock=2,
    )

    response = client.post(
        f"/inventory/products/{product['id']}/adjustments",
        json={
            "quantity_change": -3,
            "reason": "Sale",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["available_stock"] == 2

    saved = client.get(f"/products/{product['id']}")
    assert saved.json()["stock"] == 2

    history = client.get(
        "/inventory/adjustments",
        params={"product_id": product["id"]},
    )

    assert history.status_code == 200
    assert history.json() == {"adjustments": []}


def test_adjustment_product_not_found(client):
    response = client.post(
        "/inventory/products/999999/adjustments",
        json={
            "quantity_change": 1,
            "reason": "Delivery",
        },
    )

    assert response.status_code == 404

    history = client.get("/inventory/adjustments")
    assert history.status_code == 200
    assert history.json() == {"adjustments": []}


@pytest.mark.parametrize(
    "payload",
    [
        {"quantity_change": 0, "reason": "Delivery"},
        {"quantity_change": 1.5, "reason": "Delivery"},
        {"quantity_change": True, "reason": "Delivery"},
        {"quantity_change": "5", "reason": "Delivery"},
        {"quantity_change": 1_000_001, "reason": "Delivery"},
        {"quantity_change": -1_000_001, "reason": "Delivery"},
        {"quantity_change": 1, "reason": ""},
        {"quantity_change": 1, "reason": "   "},
        {"quantity_change": 1, "reason": "x" * 501},
        {"quantity_change": 1},
        {"reason": "Delivery"},
        {"quantity_change": 1, "reason": "Delivery", "unknown": 1},
    ],
)
def test_reject_invalid_adjustment(client, payload):
    product = create_product(client, stock=5)

    response = client.post(
        f"/inventory/products/{product['id']}/adjustments",
        json=payload,
    )

    assert response.status_code == 422

    saved = client.get(f"/products/{product['id']}")
    assert saved.json()["stock"] == 5

    history = client.get("/inventory/adjustments")
    assert history.json() == {"adjustments": []}


def test_adjustment_history_filter_and_pagination(client):
    first = create_product(client)
    second = create_product(client, name="Mouse", price=10)

    created_movements = []

    for product, quantity in [
        (first, 5),
        (second, 10),
        (first, -2),
    ]:
        response = client.post(
            f"/inventory/products/{product['id']}/adjustments",
            json={
                "quantity_change": quantity,
                "reason": "Inventory adjustment",
            },
        )

        assert response.status_code == 201, response.text
        created_movements.append(response.json()["adjustment"])

    response = client.get(
        "/inventory/adjustments",
        params={"product_id": first["id"]},
    )

    assert response.status_code == 200
    assert response.json()["adjustments"] == [
        created_movements[2],
        created_movements[0],
    ]

    page = client.get(
        "/inventory/adjustments",
        params={"limit": 1, "offset": 1},
    )

    assert page.status_code == 200
    assert page.json()["adjustments"] == [created_movements[1]]


def test_adjustment_history_survives_product_deletion(client):
    product = create_product(client)

    adjusted = client.post(
        f"/inventory/products/{product['id']}/adjustments",
        json={
            "quantity_change": 5,
            "reason": "Delivery",
        },
    )

    assert adjusted.status_code == 201
    movement = adjusted.json()["adjustment"]

    deleted = client.delete(f"/products/{product['id']}")
    assert deleted.status_code == 204

    history = client.get(
        "/inventory/adjustments",
        params={"product_id": product["id"]},
    )

    assert history.status_code == 200
    assert history.json()["adjustments"] == [movement]


def test_get_out_of_stock_products(client):
    first = create_product(client, stock=0)
    create_product(client, name="Mouse", price=10, stock=5)
    second = create_product(
        client,
        name="Monitor",
        price=150,
        stock=0,
    )

    response = client.get("/inventory/out-of-stock")

    assert response.status_code == 200
    assert response.json()["products"] == [first, second]

    page = client.get(
        "/inventory/out-of-stock",
        params={"limit": 1, "offset": 1},
    )

    assert page.status_code == 200
    assert page.json()["products"] == [second]


def test_inventory_summary(client):
    create_product(client, name="Keyboard", price=25, stock=2)
    create_product(client, name="Mouse", price=10, stock=0)
    create_product(client, name="Monitor", price=100, stock=5)

    response = client.get("/inventory/summary")

    assert response.status_code == 200
    assert response.json() == {
        "total_products": 3,
        "total_stock": 7,
        "inventory_value": 550,
        "out_of_stock_products": 1,
        "low_stock_products": 1,
        "low_stock_threshold": 5,
    }

    custom = client.get(
        "/inventory/summary",
        params={"low_stock_threshold": 6},
    )

    assert custom.status_code == 200
    assert custom.json()["low_stock_products"] == 2


def test_inventory_summary_empty_database(client):
    response = client.get("/inventory/summary")

    assert response.status_code == 200
    assert response.json() == {
        "total_products": 0,
        "total_stock": 0,
        "inventory_value": 0,
        "out_of_stock_products": 0,
        "low_stock_products": 0,
        "low_stock_threshold": 5,
    }


@pytest.mark.parametrize(
    "url",
    [
        "/inventory/adjustments?limit=0",
        "/inventory/adjustments?limit=501",
        "/inventory/adjustments?offset=-1",
        "/inventory/adjustments?product_id=0",
        "/inventory/out-of-stock?limit=0",
        "/inventory/out-of-stock?offset=-1",
        "/inventory/summary?low_stock_threshold=0",
    ],
)
def test_reject_invalid_inventory_query(client, url):
    response = client.get(url)

    assert response.status_code == 422

# Automatic movement history for existing product update APIs.
UPDATE_ENDPOINTS = ["put", "patch", "stock"]


def change_stock(client, product, endpoint, stock, **changes):
    url = f"/products/{product['id']}"
    if endpoint == "put":
        payload = {
            key: product[key]
            for key in ("name", "price", "category", "description", "stock")
        }
        payload.update(changes)
        payload["stock"] = stock
        return client.put(url, json=payload)
    if endpoint == "patch":
        return client.patch(url, json={**changes, "stock": stock})
    if endpoint == "stock":
        return client.patch(f"{url}/stock", json={"stock": stock})
    return client.post(
        f"/inventory/products/{product['id']}/adjustments",
        json={"quantity_change": stock - product["stock"], "reason": "Delivery"},
    )


def product_history(client, product):
    response = client.get(
        "/inventory/adjustments", params={"product_id": product["id"]}
    )
    assert response.status_code == 200
    return response.json()["adjustments"]


@pytest.mark.parametrize("endpoint", UPDATE_ENDPOINTS)
@pytest.mark.parametrize("new_stock", [0, 12])
def test_existing_stock_routes_record_exactly_one_movement(client, endpoint, new_stock):
    product = create_product(client, stock=5)
    response = change_stock(client, product, endpoint, new_stock)

    assert response.status_code == 200, response.text
    assert client.get(f"/products/{product['id']}").json() == response.json()
    movements = product_history(client, product)
    assert len(movements) == 1
    movement = movements[0]
    assert movement["product_id"] == product["id"]
    assert movement["product_name"] == product["name"]
    assert movement["previous_stock"] == 5
    assert movement["new_stock"] == new_stock
    assert movement["quantity_change"] == new_stock - 5
    assert movement["reason"]
    assert movement["created_at"].endswith("Z")


@pytest.mark.parametrize("endpoint", UPDATE_ENDPOINTS)
def test_unchanged_stock_does_not_create_movement(client, endpoint):
    product = create_product(client, stock=5)
    for _ in range(2):
        response = change_stock(client, product, endpoint, 5)
        assert response.status_code == 200, response.text
    assert product_history(client, product) == []


@pytest.mark.parametrize("method", ["put", "patch"])
def test_editing_other_fields_keeps_history_empty(client, method):
    product = create_product(client, stock=5)
    url = f"/products/{product['id']}"
    if method == "put":
        response = change_stock(client, product, "put", 5, name="New name", price=30)
    else:
        response = client.patch(url, json={"name": "New name", "price": 30})
    assert response.status_code == 200
    assert response.json()["name"] == "New name"
    assert response.json()["stock"] == 5
    assert product_history(client, product) == []


@pytest.mark.parametrize("endpoint", ["put", "patch"])
def test_movement_uses_updated_product_name(client, endpoint):
    product = create_product(client, stock=5)
    response = change_stock(client, product, endpoint, 8, name="Renamed product")
    assert response.status_code == 200
    assert product_history(client, product)[0]["product_name"] == "Renamed product"


def test_mixed_stock_updates_produce_continuous_history(client):
    product = create_product(client, stock=5)
    for endpoint, stock in [("put", 12), ("patch", 8), ("stock", 0), ("adjustment", 3)]:
        response = change_stock(client, product, endpoint, stock)
        assert response.status_code in (200, 201), response.text
        product = client.get(f"/products/{product['id']}").json()

    movements = list(reversed(product_history(client, product)))
    assert [(m["previous_stock"], m["new_stock"], m["quantity_change"]) for m in movements] == [
        (5, 12, 7), (12, 8, -4), (8, 0, -8), (0, 3, 3)
    ]


@pytest.mark.parametrize("endpoint", [*UPDATE_ENDPOINTS, "adjustment"])
def test_failed_history_insert_rolls_back_product_update(client, endpoint):
    product = create_product(client, stock=5)
    # Fail the actual SQLite insert after the product UPDATE has executed.
    with main.database() as connection:
        connection.execute("""
            CREATE TRIGGER reject_movement
            BEFORE INSERT ON stock_adjustments
            BEGIN
                SELECT RAISE(ABORT, 'Simulated history write failure');
            END
        """)

    with TestClient(main.app, raise_server_exceptions=False) as failing_client:
        metadata = {"name": "Should roll back", "price": 99} if endpoint in ("put", "patch") else {}
        response = change_stock(failing_client, product, endpoint, 8, **metadata)

    assert response.status_code == 500
    assert client.get(f"/products/{product['id']}").json() == product
    assert product_history(client, product) == []


@pytest.mark.parametrize("endpoint", UPDATE_ENDPOINTS)
@pytest.mark.parametrize("stock", [-1, 1.5, True, 9_223_372_036_854_775_808])
def test_invalid_absolute_stock_changes_nothing(client, endpoint, stock):
    product = create_product(client, stock=5)
    response = change_stock(client, product, endpoint, stock)
    assert response.status_code == 422
    assert client.get(f"/products/{product['id']}").json() == product
    assert product_history(client, product) == []


@pytest.mark.parametrize("endpoint", UPDATE_ENDPOINTS)
def test_update_missing_product_creates_no_movement(client, endpoint):
    product = {
        "id": 999999, "name": "Missing", "price": 25,
        "category": "General", "description": "", "stock": 5,
    }
    response = change_stock(client, product, endpoint, 8)
    assert response.status_code == 404
    assert product_history(client, product) == []


def test_existing_database_migration_preserves_products(tmp_path, monkeypatch):
    import sqlite3

    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("""
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL CHECK (price > 0)
            )
        """)
        connection.execute("INSERT INTO products (name, price) VALUES ('Existing', 10)")
    monkeypatch.setattr(main, "DB_PATH", path)

    with TestClient(main.app) as legacy_client:
        response = legacy_client.get("/products/1")
        assert response.status_code == 200
        product = response.json()
        assert product["name"] == "Existing"
        assert product["stock"] == 0
        updated = change_stock(legacy_client, product, "stock", 4)
        assert updated.status_code == 200
        assert len(product_history(legacy_client, product)) == 1


def test_concurrent_absolute_updates_keep_history_consistent(client):
    from concurrent.futures import ThreadPoolExecutor

    product = create_product(client, stock=5)
    with ThreadPoolExecutor(max_workers=3) as executor:
        responses = list(executor.map(
            lambda amount: change_stock(client, product, "stock", amount),
            [10, 20, 30],
        ))
    assert all(response.status_code == 200 for response in responses)
    movements = list(reversed(product_history(client, product)))
    assert len(movements) == 3
    previous_stock = 5
    for movement in movements:
        assert movement["previous_stock"] == previous_stock
        assert movement["quantity_change"] == movement["new_stock"] - previous_stock
        previous_stock = movement["new_stock"]
    assert client.get(f"/products/{product['id']}").json()["stock"] == previous_stock
