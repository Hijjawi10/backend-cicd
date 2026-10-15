from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def home():
    return {"message": "Backend is running"}


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.1"}