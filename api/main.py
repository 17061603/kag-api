import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager
from routers import project_router, file_router, schema_router, builder_router
from database.connection import init_db, close_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title="KAG Project API",
    description="KAG项目管理的API接口",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(project_router)
app.include_router(file_router)
app.include_router(schema_router)
app.include_router(builder_router)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

