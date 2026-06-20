from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.database import engine, SessionLocal, Base
from app.routers import fermenters, recipes, batches, readings, alerts, progress, stats
from app.seed import seed_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()
    yield
    pass


app = FastAPI(
    title="精酿啤酒发酵过程监控与批次质控服务",
    description="""
    ## 功能模块

    - **发酵罐管理**: 发酵罐的增删改查，删除时发酵中状态拒绝
    - **啤酒配方管理**: 配方管理，包含温度曲线阶段
    - **批次管理**: 开始/结束批次，自动生成批次号
    - **数据采集**: 传感器读数上报，自动判定阶段，异常检测
    - **告警系统**: 温度偏差和发酵停滞告警，支持确认和关闭
    - **发酵进度**: 实时进度查询，质控报告
    - **统计分析**: 罐利用率、配方统计、告警频率

    启动时已预置 5 个发酵罐、3 个配方、2 个进行中批次（含告警）和 1 个已完成批次（含质控报告）。
    """,
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(fermenters.router)
app.include_router(recipes.router)
app.include_router(batches.router)
app.include_router(readings.router)
app.include_router(alerts.router)
app.include_router(progress.router)
app.include_router(stats.router)


@app.get("/", tags=["根路径"])
def root():
    return {
        "service": "精酿啤酒发酵过程监控与批次质控服务",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
    }


@app.get("/health", tags=["健康检查"])
def health_check():
    return {"status": "ok"}
