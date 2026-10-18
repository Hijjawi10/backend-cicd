import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

app = FastAPI()

DB_PATH = Path(__file__).resolve().parent / "products.db"


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    price: float = Field(gt=0, allow_inf_nan=False)
    category: str = Field(default="General", min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    stock: int = Field(default=0, ge=0)


class StockUpdate(BaseModel):
    stock: int = Field(ge=0)


@contextmanager
def database():
    connection = sqlite3.connect(str(DB_PATH), timeout=10)
    connection.row_factory = sqlite3.Row

    try:
        connection.execute("BEGIN IMMEDIATE")

        connection.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL CHECK (price > 0)
            )
        """)

        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(products)")
        }

        if "category" not in columns:
            connection.execute("""
                ALTER TABLE products
                ADD COLUMN category TEXT NOT NULL DEFAULT 'General'
            """)

        if "description" not in columns:
            connection.execute("""
                ALTER TABLE products
                ADD COLUMN description TEXT NOT NULL DEFAULT ''
            """)

        if "stock" not in columns:
            connection.execute("""
                ALTER TABLE products
                ADD COLUMN stock INTEGER NOT NULL DEFAULT 0
                CHECK (stock >= 0)
            """)

        yield connection
        connection.commit()

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def find_product(connection, product_id):
    row = connection.execute(
        "SELECT * FROM products WHERE id = ?",
        (product_id,)
    ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Product not found")

    return dict(row)


@app.get("/")
def home():
    return {"message": "Backend is running"}


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.1.0"}


@app.get("/products")
def get_products(
    name: str | None = None,
    category: str | None = None,
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    in_stock: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    if (
        min_price is not None
        and max_price is not None
        and min_price > max_price
    ):
        raise HTTPException(
            status_code=422,
            detail="min_price must not exceed max_price"
        )

    sql = "SELECT * FROM products WHERE 1 = 1"
    parameters = []

    if name is not None:
        sql += " AND instr(lower(name), lower(?)) > 0"
        parameters.append(name)

    if category is not None:
        sql += " AND category = ?"
        parameters.append(category)

    if min_price is not None:
        sql += " AND price >= ?"
        parameters.append(min_price)

    if max_price is not None:
        sql += " AND price <= ?"
        parameters.append(max_price)

    if in_stock:
        sql += " AND stock > 0"

    sql += " ORDER BY id LIMIT ? OFFSET ?"
    parameters.extend([limit, offset])

    with database() as connection:
        rows = connection.execute(sql, parameters).fetchall()

    return {"products": [dict(row) for row in rows]}


@app.get("/products/stats")
def get_product_stats():
    with database() as connection:
        row = connection.execute("""
            SELECT
                COUNT(*) AS total_products,
                COALESCE(SUM(stock), 0) AS total_stock,
                COALESCE(SUM(price * stock), 0) AS inventory_value,
                COALESCE(AVG(price), 0) AS average_price
            FROM products
        """).fetchone()

    return dict(row)


@app.get("/products/{product_id}")
def get_product(product_id: int):
    with database() as connection:
        return find_product(connection, product_id)


@app.post("/products", status_code=201)
def create_product(product: ProductCreate):
    with database() as connection:
        cursor = connection.execute(
            """
            INSERT INTO products
                (name, price, category, description, stock)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                product.name,
                product.price,
                product.category,
                product.description,
                product.stock,
            )
        )

        return find_product(connection, cursor.lastrowid)


@app.put("/products/{product_id}")
def update_product(product_id: int, product: ProductCreate):
    with database() as connection:
        find_product(connection, product_id)

        connection.execute(
            """
            UPDATE products
            SET name = ?, price = ?, category = ?,
                description = ?, stock = ?
            WHERE id = ?
            """,
            (
                product.name,
                product.price,
                product.category,
                product.description,
                product.stock,
                product_id,
            )
        )

        return find_product(connection, product_id)


@app.patch("/products/{product_id}/stock")
def update_stock(product_id: int, update: StockUpdate):
    with database() as connection:
        find_product(connection, product_id)

        connection.execute(
            "UPDATE products SET stock = ? WHERE id = ?",
            (update.stock, product_id)
        )

        return find_product(connection, product_id)


@app.get("/get_products_by_name/{products_name}")
def get_products_by_name(products_name: str):
    with database() as connection:
        rows = connection.execute(
            "SELECT * FROM products WHERE name = ? ORDER BY id",
            (products_name,)
        ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="Product not found")

    return {"products": [dict(row) for row in rows]}


@app.get("/get_products_by_price/{products_price}")
def get_products_by_price(products_price: float):
    with database() as connection:
        rows = connection.execute(
            "SELECT * FROM products WHERE price = ? ORDER BY id",
            (products_price,)
        ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="Product not found")

    return {"products": [dict(row) for row in rows]}


@app.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: int):
    with database() as connection:
        cursor = connection.execute(
            "DELETE FROM products WHERE id = ?",
            (product_id,)
        )

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Product not found")