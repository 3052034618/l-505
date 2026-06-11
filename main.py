from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, date, timedelta
import logging

from config import settings
from database import engine, get_db, SessionLocal
import models

from routers.auth import router as auth_router, router_users
from routers.base import router_labs, router_chemicals, router_cabinets, router_inventory
from routers.inbound import router_inbound
from routers.usage import router_usage
from routers.alarm import router_sensors, router_alarms, router_plans
from routers.waste import router_waste, router_disposal, router_replenishment
from routers.report import router_report, router_notification, generate_all_daily_reports
from routers.websocket import router_ws
from routers.events import router_events, router_audits
from routers.dashboard import router_dashboard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_daily_report_generation():
    try:
        db = SessionLocal()
        try:
            yesterday = date.today() - timedelta(days=1)
            reports = generate_all_daily_reports(db, yesterday)
            logger.info(f"[{datetime.now()}] 定时任务：生成日报 {len(reports)} 份 (日期: {yesterday})")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"日报生成任务出错: {e}")


def run_replenishment_reminder():
    try:
        db = SessionLocal()
        try:
            from reminder_service import process_all_reminders
            result = process_all_reminders(db)
            if result.get("total_reminded", 0) > 0:
                logger.info(
                    f"[{datetime.now()}] 定时任务：统一催办  reminded={result.get('total_reminded')} "
                    f"escalated={result.get('total_escalated')}  detail={result.get('detail')}"
                )
        finally:
            db.close()
    except Exception as e:
        logger.error(f"统一催办任务出错: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    models.Base.metadata.create_all(bind=engine)
    logger.info(f"数据库表已创建/校验完成")

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_daily_report_generation,
        'cron',
        hour=settings.DAILY_REPORT_HOUR,
        minute=settings.DAILY_REPORT_MINUTE,
        id='daily_report_job',
        replace_existing=True
    )
    scheduler.add_job(
        run_replenishment_reminder,
        'cron',
        hour='9,15,21',
        minute=0,
        id='replenishment_reminder_job',
        replace_existing=True
    )
    scheduler.start()
    logger.info("定时任务调度器已启动 (每日凌晨生成日报 / 每日3次补货催办)")

    yield

    scheduler.shutdown()
    logger.info("调度器已关闭")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## 智慧实验室危险化学品全流程监管与应急调度系统

### 核心功能模块

1. **危化品入库** - MSDS自动校验、智能柜位分配、温湿度阈值绑定
2. **领用申请** - 资质审核、用量偏差校验、导师审批、替代方案建议
3. **实时监测与告警** - 传感器数据接入、分级告警、应急预案匹配、任务分配
4. **废液回收** - 密封性/标签检查、转运批次生成、处理中心关联
5. **库存补货** - 安全水位监控、两级审批（主任+安环）、超时自动催办
6. **日报统计** - 每日凌晨自动生成、分类统计、按日期/实验室导出
7. **实时推送** - WebSocket实时推送入库/领用/告警/回收状态

### 用户角色

- **admin** - 系统管理员（最高权限）
- **lab_manager** - 实验室主任（补货审批等）
- **safety_officer** - 安全管理员/安环部门（MSDS、告警、补货审批）
- **emergency_team** - 应急小组（处理告警任务）
- **supervisor** - 导师（审批领用申请）
- **researcher** - 实验人员/研究员（基础操作）
    """,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["系统"])
def root():
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "redoc": "/redoc",
        "status": "running"
    }


@app.get("/api/health", tags=["系统"])
def health_check(db: Session = Depends(get_db)):
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        return {
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "database": f"error: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        }


app.include_router(auth_router)
app.include_router(router_users)
app.include_router(router_labs)
app.include_router(router_chemicals)
app.include_router(router_cabinets)
app.include_router(router_inventory)
app.include_router(router_inbound)
app.include_router(router_usage)
app.include_router(router_sensors)
app.include_router(router_alarms)
app.include_router(router_plans)
app.include_router(router_waste)
app.include_router(router_disposal)
app.include_router(router_replenishment)
app.include_router(router_report)
app.include_router(router_notification)
app.include_router(router_ws)
app.include_router(router_events)
app.include_router(router_audits)
app.include_router(router_dashboard)
