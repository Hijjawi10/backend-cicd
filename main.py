import sqlite3
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator


app = FastAPI()

DB_PATH = Path(__file__).resolve().parent / "products.db"



@contextmanager
def database():
    connection = sqlite3.connect(str(DB_PATH), timeout=10)
    connection.row_factory = sqlite3.Row

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database():
    with database() as connection:
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Products API",
    version="1.1.0",
    lifespan=lifespan,
)



class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=150)
    price: float = Field(gt=0, allow_inf_nan=False)
    category: str = Field(default="General", min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    stock: int = Field(default=0, ge=0, strict=True)

    @field_validator("name", "category", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class ProductPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    category: str | None = Field(
        default=None, min_length=1, max_length=100
    )
    description: str | None = Field(default=None, max_length=1000)
    stock: int | None = Field(default=None, ge=0, strict=True)

    @field_validator("name", "category", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class StockUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stock: int = Field(ge=0, strict=True)



def find_product(connection, product_id: int):
    row = connection.execute(
        "SELECT * FROM products WHERE id = ?",
        (product_id,),
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
    min_price: float | None = Query(
        default=None, ge=0, allow_inf_nan=False
    ),
    max_price: float | None = Query(
        default=None, ge=0, allow_inf_nan=False
    ),
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
            detail="min_price must not exceed max_price",
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


@app.get("/products/low-stock")
def get_low_stock(
    threshold: int = Query(default=5, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    with database() as connection:
        rows = connection.execute(
            """
            SELECT * FROM products
            WHERE stock < ?
            ORDER BY stock, id
            LIMIT ? OFFSET ?
            """,
            (threshold, limit, offset),
        ).fetchall()

    return {"products": [dict(row) for row in rows]}


@app.get("/categories")
def get_categories():
    with database() as connection:
        rows = connection.execute(
            "SELECT DISTINCT category FROM products ORDER BY category"
        ).fetchall()

    return {"categories": [row["category"] for row in rows]}


@app.get("/reports/categories")
def get_category_report():
    with database() as connection:
        rows = connection.execute("""
            SELECT
                category,
                COUNT(*) AS total_products,
                COALESCE(SUM(stock), 0) AS total_stock,
                COALESCE(SUM(price * stock), 0) AS inventory_value
            FROM products
            GROUP BY category
            ORDER BY category
        """).fetchall()

    return {"categories": [dict(row) for row in rows]}



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
            ),
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
            ),
        )

        return find_product(connection, product_id)


@app.patch("/products/{product_id}")
def patch_product(product_id: int, product: ProductPatch):
    changes = product.model_dump(exclude_unset=True)

    if not changes:
        raise HTTPException(
            status_code=422,
            detail="Send at least one field to update",
        )

    if any(value is None for value in changes.values()):
        raise HTTPException(
            status_code=422,
            detail="Product fields cannot be null",
        )

    # Column names come only from the validated model.
    assignments = ", ".join(f"{field} = ?" for field in changes)
    parameters = [*changes.values(), product_id]

    with database() as connection:
        find_product(connection, product_id)

        connection.execute(
            f"UPDATE products SET {assignments} WHERE id = ?",
            parameters,
        )

        return find_product(connection, product_id)


@app.patch("/products/{product_id}/stock")
def update_stock(product_id: int, update: StockUpdate):
    with database() as connection:
        find_product(connection, product_id)

        connection.execute(
            "UPDATE products SET stock = ? WHERE id = ?",
            (update.stock, product_id),
        )

        return find_product(connection, product_id)


@app.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: int):
    with database() as connection:
        cursor = connection.execute(
            "DELETE FROM products WHERE id = ?",
            (product_id,),
        )

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Product not found")

    return Response(status_code=204)



@app.get("/get_products_by_name/{products_name}")
def get_products_by_name(products_name: str):
    with database() as connection:
        rows = connection.execute(
            "SELECT * FROM products WHERE name = ? ORDER BY id",
            (products_name,),
        ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="Product not found")

    return {"products": [dict(row) for row in rows]}


@app.get("/get_products_by_price/{products_price}")
def get_products_by_price(products_price: float):
    with database() as connection:
        rows = connection.execute(
            "SELECT * FROM products WHERE price = ? ORDER BY id",
            (products_price,),
        ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="Product not found")

    return {"products": [dict(row) for row in rows]}