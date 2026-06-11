from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from datetime import date, datetime
from typing import List, Optional
import models
import schemas
from database import get_db
from routers.auth import get_current_user, require_roles

router_dashboard = APIRouter(prefix="/api/dashboard", tags=["监管总览"])


@router_dashboard.get("/overview", response_model=schemas.DashboardOverviewResponse)
def get_dashboard_overview(
    lab_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    监管总览看板：按实验室汇总待审批、告警、低库存、废液、今日出入库。
    权限：
      - ADMIN：看全部（可指定lab_id）
      - LAB_MANAGER：只看自己所在实验室（忽略传入lab_id）
      - SAFETY_OFFICER：看全部实验室（不限制）
      - 其他：无权限
    """
    # 权限过滤
    if current_user.role == models.UserRole.LAB_MANAGER:
        allowed_lab_ids = [current_user.lab_id]
    elif current_user.role in [models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER]:
        if lab_id:
            allowed_lab_ids = [lab_id]
        else:
            labs = db.query(models.Laboratory).filter(models.Laboratory.is_active == True).all()
            allowed_lab_ids = [l.id for l in labs]
    else:
        allowed_lab_ids = [current_user.lab_id] if current_user.lab_id else []

    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())

    def _q_in(model_cls, lab_field):
        return db.query(model_cls).filter(getattr(model_cls, lab_field).in_(allowed_lab_ids))

    # ---------- 待审批 ----------
    # 领用-导师待批
    usage_supervisor_pending = _q_in(models.UsageRequest, "lab_id").filter(
        models.UsageRequest.status == models.RequestStatus.SUPERVISOR_PENDING
    ).count()
    # 补货-主任待批
    replenish_lab_pending = db.query(models.ReplenishmentRequest).join(
        models.Chemical, models.ReplenishmentRequest.chemical_id == models.Chemical.id
    ).filter(
        models.Chemical.lab_id.in_(allowed_lab_ids),
        models.ReplenishmentRequest.status == models.ReplenishmentStatus.PENDING_LAB_MANAGER
    ).count()
    # 补货-安环待批
    replenish_safety_pending = db.query(models.ReplenishmentRequest).join(
        models.Chemical, models.ReplenishmentRequest.chemical_id == models.Chemical.id
    ).filter(
        models.Chemical.lab_id.in_(allowed_lab_ids),
        models.ReplenishmentRequest.status == models.ReplenishmentStatus.PENDING_SAFETY
    ).count()
    # 废液-待检查
    waste_pending_inspection = _q_in(models.WasteRecord, "lab_id").filter(
        models.WasteRecord.status == models.WasteStatus.PENDING_INSPECTION
    ).count()

    # ---------- 告警 ----------
    alarm_triggered = _q_in(models.Alarm, "lab_id").filter(
        models.Alarm.status.in_([models.AlarmStatus.TRIGGERED, models.AlarmStatus.ACKNOWLEDGED])
    ).count()
    alarm_handling = _q_in(models.Alarm, "lab_id").filter(
        models.Alarm.status == models.AlarmStatus.HANDLING
    ).count()
    alarm_tasks_assigned = db.query(models.AlarmTask).join(
        models.Alarm, models.AlarmTask.alarm_id == models.Alarm.id
    ).filter(
        models.Alarm.lab_id.in_(allowed_lab_ids),
        models.AlarmTask.status == models.TaskStatus.ASSIGNED
    ).count()

    # ---------- 低库存 ----------
    low_stock_count = db.query(models.Inventory).join(
        models.Chemical, models.Inventory.chemical_id == models.Chemical.id
    ).filter(
        models.Chemical.lab_id.in_(allowed_lab_ids),
        models.Inventory.current_quantity > 0,
        models.Inventory.current_quantity <= models.Inventory.safety_level
    ).count()

    # ---------- 今日入库/领用变化 ----------
    today_inbound_approved = db.query(models.InboundRecord).join(
        models.Chemical, models.InboundRecord.chemical_id == models.Chemical.id
    ).filter(
        models.Chemical.lab_id.in_(allowed_lab_ids),
        models.InboundRecord.created_at >= today_start,
        models.InboundRecord.status == "approved"
    ).count()
    today_inbound_total = db.query(models.InboundRecord).join(
        models.Chemical, models.InboundRecord.chemical_id == models.Chemical.id
    ).filter(
        models.Chemical.lab_id.in_(allowed_lab_ids),
        models.InboundRecord.created_at >= today_start
    ).count()

    today_usage_approved = _q_in(models.UsageRequest, "lab_id").filter(
        models.UsageRequest.created_at >= today_start,
        models.UsageRequest.status.in_([
            models.RequestStatus.AUTO_APPROVED,
            models.RequestStatus.SUPERVISOR_APPROVED,
            models.RequestStatus.COMPLETED
        ])
    ).count()
    today_usage_total = _q_in(models.UsageRequest, "lab_id").filter(
        models.UsageRequest.created_at >= today_start
    ).count()

    # ---------- 废液流转中 ----------
    waste_batched = _q_in(models.WasteRecord, "lab_id").filter(
        models.WasteRecord.status == models.WasteStatus.BATCHED
    ).count()
    waste_in_transit = _q_in(models.WasteRecord, "lab_id").filter(
        models.WasteRecord.status == models.WasteStatus.IN_TRANSIT
    ).count()
    today_waste_submitted = _q_in(models.WasteRecord, "lab_id").filter(
        models.WasteRecord.created_at >= today_start
    ).count()

    # ---------- 按实验室细粒度汇总 ----------
    lab_breakdown: List[schemas.DashboardLabSummary] = []
    for lid in allowed_lab_ids:
        lab = db.query(models.Laboratory).filter(models.Laboratory.id == lid).first()
        if not lab:
            continue

        lab_usage_sv = db.query(models.UsageRequest).filter(
            models.UsageRequest.lab_id == lid,
            models.UsageRequest.status == models.RequestStatus.SUPERVISOR_PENDING
        ).count()
        lab_rep_lab = db.query(models.ReplenishmentRequest).join(
            models.Chemical, models.ReplenishmentRequest.chemical_id == models.Chemical.id
        ).filter(
            models.Chemical.lab_id == lid,
            models.ReplenishmentRequest.status == models.ReplenishmentStatus.PENDING_LAB_MANAGER
        ).count()
        lab_rep_safety = db.query(models.ReplenishmentRequest).join(
            models.Chemical, models.ReplenishmentRequest.chemical_id == models.Chemical.id
        ).filter(
            models.Chemical.lab_id == lid,
            models.ReplenishmentRequest.status == models.ReplenishmentStatus.PENDING_SAFETY
        ).count()
        lab_waste_pending = db.query(models.WasteRecord).filter(
            models.WasteRecord.lab_id == lid,
            models.WasteRecord.status == models.WasteStatus.PENDING_INSPECTION
        ).count()
        lab_alarm_active = db.query(models.Alarm).filter(
            models.Alarm.lab_id == lid,
            models.Alarm.status.in_([
                models.AlarmStatus.TRIGGERED,
                models.AlarmStatus.ACKNOWLEDGED,
                models.AlarmStatus.HANDLING
            ])
        ).count()
        lab_low_stock = db.query(models.Inventory).join(
            models.Chemical, models.Inventory.chemical_id == models.Chemical.id
        ).filter(
            models.Chemical.lab_id == lid,
            models.Inventory.current_quantity > 0,
            models.Inventory.current_quantity <= models.Inventory.safety_level
        ).count()

        lab_breakdown.append(schemas.DashboardLabSummary(
            lab_id=lab.id,
            lab_code=lab.code,
            lab_name=lab.name,
            pending_usage_supervisor=lab_usage_sv,
            pending_replenish_lab_manager=lab_rep_lab,
            pending_replenish_safety=lab_rep_safety,
            pending_waste_inspection=lab_waste_pending,
            active_alarms=lab_alarm_active,
            low_stock_items=lab_low_stock,
            # 各卡片跳转链接
            links=schemas.DashboardLinks(
                usage_supervisor_pending=f"/usage?status=supervisor_pending&lab_id={lab.id}",
                replenish_lab_manager_pending=f"/replenishment?status=pending_lab_manager&lab_id={lab.id}",
                replenish_safety_pending=f"/replenishment?status=pending_safety&lab_id={lab.id}",
                waste_pending_inspection=f"/waste?status=pending_inspection&lab_id={lab.id}",
                active_alarms=f"/alarm?status=active&lab_id={lab.id}",
                low_stock=f"/inventory?low_stock=true&lab_id={lab.id}",
                today_inbound=f"/inbound?date={today}&lab_id={lab.id}",
                today_usage=f"/usage?date={today}&lab_id={lab.id}",
                today_waste=f"/waste?date={today}&lab_id={lab.id}",
            )
        ))

    return schemas.DashboardOverviewResponse(
        generated_at=datetime.utcnow().isoformat(),
        scope_lab_ids=allowed_lab_ids,
        viewer_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        viewer_id=current_user.id,
        viewer_name=current_user.real_name,
        pending_approvals=schemas.DashboardPendingApprovals(
            usage_supervisor=usage_supervisor_pending,
            replenish_lab_manager=replenish_lab_pending,
            replenish_safety=replenish_safety_pending,
            waste_inspection=waste_pending_inspection,
            total=usage_supervisor_pending + replenish_lab_pending + replenish_safety_pending + waste_pending_inspection,
        ),
        active_alarms=schemas.DashboardActiveAlarms(
            triggered=alarm_triggered,
            handling=alarm_handling,
            tasks_assigned=alarm_tasks_assigned,
            total=alarm_triggered + alarm_handling,
        ),
        inventory=schemas.DashboardInventory(
            low_stock_items=low_stock_count,
        ),
        waste=schemas.DashboardWasteSummary(
            pending_inspection=waste_pending_inspection,
            batched=waste_batched,
            in_transit=waste_in_transit,
            submitted_today=today_waste_submitted,
        ),
        today=schemas.DashboardTodayStats(
            date=today.isoformat(),
            inbound_approved=today_inbound_approved,
            inbound_total=today_inbound_total,
            usage_approved=today_usage_approved,
            usage_total=today_usage_total,
            waste_submitted=today_waste_submitted,
        ),
        lab_breakdown=lab_breakdown,
    )


@router_dashboard.post("/trigger-reminders", dependencies=[Depends(require_roles(models.UserRole.ADMIN))])
def trigger_reminders(db: Session = Depends(get_db)):
    """手动触发超时催办引擎（admin权限），方便测试"""
    from reminder_service import process_all_reminders
    return process_all_reminders(db)
