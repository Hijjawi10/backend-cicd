import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()

DB_PATH = Path(__file__).resolve().parent / "products.db"


class ProductCreate(BaseModel):
    name: str = Field(min_length=1)
    price: float = Field(gt=0)


@contextmanager
def database():
    connection = sqlite3.connect(str(DB_PATH), timeout=10)
    connection.row_factory = sqlite3.Row

    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL CHECK (price > 0)
            )
        """)

        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@app.get("/")
def home():
    return {"message": "Backend is running"}


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.1.0"}


@app.get("/products")
def get_products():
    with database() as connection:
        rows = connection.execute(
            "SELECT id, name, price FROM products ORDER BY id"
        ).fetchall()

    return {"products": [dict(row) for row in rows]}


@app.get("/products/{product_id}")
def get_product(product_id: int):
    with database() as connection:
        row = connection.execute(
            "SELECT id, name, price FROM products WHERE id = ?",
            (product_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Product not found")

    return dict(row)


@app.post("/products", status_code=201)
def create_product(product: ProductCreate):
    with database() as connection:
        cursor = connection.execute(
            "INSERT INTO products (name, price) VALUES (?, ?)",
            (product.name, product.price)
        )

        new_product = {
            "id": cursor.lastrowid,
            "name": product.name,
            "price": product.price
        }

    return new_product