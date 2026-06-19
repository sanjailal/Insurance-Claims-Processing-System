from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.database import create_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


app = FastAPI(
    title="Insurance Claims Processing System",
    description="Adjudicates insurance claims against policy coverage rules.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)
