from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()


class ProductCreate(BaseModel):
    name: str = Field(min_length=1)
    price: float = Field(gt=0)


products = [
    {"id": 1, "name": "Laptop", "price": 500.0},
    {"id": 2, "name": "Mouse", "price": 10.0},
]


@app.get("/")
def home():
    return {"message": "Backend is running"}


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.1"}


@app.get("/products")
def get_products():
    return {"products": products}


@app.get("/products/{product_id}")
def get_product(product_id: int):
    for product in products:
        if product["id"] == product_id:
            return product

    raise HTTPException(status_code=404, detail="Product not found")


@app.post("/products", status_code=201)
def create_product(product: ProductCreate):
    new_product = {
        "id": max((item["id"] for item in products), default=0) + 1,
        "name": product.name,
        "price": product.price,
    }

    products.append(new_product)
    return new_product