from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from database import get_db
from auth import get_current_user, require_roles
import models
import schemas

router_events = APIRouter(prefix="/api/events", tags=["事件中心"])
router_audits = APIRouter(prefix="/api/audit-trails", tags=["审批流转痕迹"])


@router_events.get("", response_model=List[schemas.EventLogResponse])
def list_events(
    business_type: Optional[str] = None,
    event_type: Optional[str] = None,
    lab_id: Optional[int] = None,
    handle_status: Optional[str] = None,
    operator_id: Optional[int] = None,
    target_role: Optional[str] = None,
    target_user_id: Optional[int] = None,
    business_no: Optional[str] = None,
    hours: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.EventLog)

    if current_user.role not in [models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER]:
        lab_condition = models.EventLog.lab_id == current_user.lab_id
        target_user_condition = models.EventLog.target_user_id == current_user.id
        user_role_str = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        role_condition = models.EventLog.target_role == user_role_str
        query = query.filter((lab_condition) | (target_user_condition) | (role_condition))

    if business_type:
        query = query.filter(models.EventLog.business_type == business_type)
    if event_type:
        query = query.filter(models.EventLog.event_type == event_type)
    if lab_id:
        query = query.filter(models.EventLog.lab_id == lab_id)
    if handle_status:
        query = query.filter(models.EventLog.handle_status == handle_status)
    if operator_id:
        query = query.filter(models.EventLog.operator_id == operator_id)
    if target_role:
        query = query.filter(models.EventLog.target_role == target_role)
    if target_user_id:
        query = query.filter(models.EventLog.target_user_id == target_user_id)
    if business_no:
        query = query.filter(models.EventLog.business_no.like(f"%{business_no}%"))
    if hours:
        since = datetime.utcnow() - timedelta(hours=hours)
        query = query.filter(models.EventLog.created_at >= since)

    return query.order_by(models.EventLog.created_at.desc()).offset(skip).limit(limit).all()


@router_events.get("/{event_id}", response_model=schemas.EventLogResponse)
def get_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    ev = db.query(models.EventLog).filter(models.EventLog.id == event_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="事件不存在")

    if current_user.role not in [models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER]:
        user_role_str = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        if (
            ev.lab_id != current_user.lab_id
            and ev.target_user_id != current_user.id
            and ev.target_role != user_role_str
        ):
            raise HTTPException(status_code=403, detail="无权查看此事件")
    return ev


@router_events.put("/{event_id}/status", response_model=schemas.EventLogResponse)
def update_event_status(
    event_id: int,
    handle_status: str = "completed",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(
        models.UserRole.ADMIN,
        models.UserRole.SAFETY_OFFICER,
        models.UserRole.LAB_MANAGER,
        models.UserRole.EMERGENCY_TEAM
    )),
):
    ev = db.query(models.EventLog).filter(models.EventLog.id == event_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="事件不存在")
    valid = [s.value for s in models.EventHandleStatus]
    if handle_status not in valid:
        raise HTTPException(status_code=400, detail=f"状态无效，有效值: {valid}")
    ev.handle_status = handle_status
    db.commit()
    db.refresh(ev)
    return ev


@router_events.get("/stats/summary", response_model=Dict[str, Any])
def get_event_summary(
    hours: int = 24,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    since = datetime.utcnow() - timedelta(hours=hours)
    base = db.query(models.EventLog).filter(models.EventLog.created_at >= since)
    if current_user.role not in [models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER]:
        user_role_str = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        base = base.filter(
            (models.EventLog.lab_id == current_user.lab_id)
            | (models.EventLog.target_user_id == current_user.id)
            | (models.EventLog.target_role == user_role_str)
        )

    total = base.count()
    by_business = {}
    for row in base.with_entities(
        models.EventLog.business_type,
        func.count(models.EventLog.id)
    ).group_by(models.EventLog.business_type).all():
        bt = row[0].value if hasattr(row[0], "value") else str(row[0])
        by_business[bt] = row[1]

    by_status = {}
    for row in base.with_entities(
        models.EventLog.handle_status,
        func.count(models.EventLog.id)
    ).group_by(models.EventLog.handle_status).all():
        hs = row[0].value if hasattr(row[0], "value") else str(row[0])
        by_status[hs] = row[1]

    pending_count = by_status.get("pending", 0)
    handling_count = by_status.get("handling", 0)
    completed_count = by_status.get("completed", 0)

    return {
        "hours": hours,
        "total": total,
        "pending": pending_count,
        "handling": handling_count,
        "completed": completed_count,
        "by_business_type": by_business,
        "by_handle_status": by_status,
    }


@router_audits.get("", response_model=List[schemas.AuditTrailResponse])
def list_audit_trails(
    business_type: Optional[str] = None,
    business_id: Optional[int] = None,
    business_no: Optional[str] = None,
    operator_id: Optional[int] = None,
    action: Optional[str] = None,
    hours: Optional[int] = None,
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.AuditTrail)

    if current_user.role not in [models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER]:
        from sqlalchemy import or_
        subq = db.query(models.EventLog.business_id, models.EventLog.business_type).filter(
            (models.EventLog.lab_id == current_user.lab_id)
            | (models.EventLog.target_user_id == current_user.id)
        ).subquery()
        query = query.filter(
            or_(
                models.AuditTrail.operator_id == current_user.id,
                (models.AuditTrail.business_id == subq.c.business_id)
                & (models.AuditTrail.business_type == subq.c.business_type),
            )
        )

    if business_type:
        query = query.filter(models.AuditTrail.business_type == business_type)
    if business_id:
        query = query.filter(models.AuditTrail.business_id == business_id)
    if business_no:
        query = query.filter(models.AuditTrail.business_no.like(f"%{business_no}%"))
    if operator_id:
        query = query.filter(models.AuditTrail.operator_id == operator_id)
    if action:
        query = query.filter(models.AuditTrail.action.like(f"%{action}%"))
    if hours:
        since = datetime.utcnow() - timedelta(hours=hours)
        query = query.filter(models.AuditTrail.created_at >= since)

    return query.order_by(models.AuditTrail.created_at.desc()).offset(skip).limit(limit).all()


@router_audits.get("/business/{business_type}/{business_id}", response_model=List[schemas.AuditTrailResponse])
def get_audits_for_business(
    business_type: str,
    business_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.AuditTrail).filter(
        models.AuditTrail.business_type == business_type,
        models.AuditTrail.business_id == business_id,
    )
    trails = query.order_by(models.AuditTrail.created_at.asc()).all()

    if current_user.role not in [models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER]:
        if trails:
            t0 = trails[0]
            ev = db.query(models.EventLog).filter(
                models.EventLog.business_type == t0.business_type,
                models.EventLog.business_id == t0.business_id,
            ).first()
            user_role_str = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
            if ev and (
                ev.lab_id != current_user.lab_id
                and ev.target_user_id != current_user.id
                and ev.target_role != user_role_str
            ):
                raise HTTPException(status_code=403, detail="无权查看此审批痕迹")
    return trails


@router_audits.get("/stats/duration", response_model=Dict[str, Any])
def get_stage_duration_stats(
    business_type: Optional[str] = None,
    days: int = 7,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER, models.UserRole.LAB_MANAGER)),
):
    since = datetime.utcnow() - timedelta(days=days)
    query = db.query(models.AuditTrail).filter(models.AuditTrail.created_at >= since)
    if business_type:
        query = query.filter(models.AuditTrail.business_type == business_type)
    if current_user.role == models.UserRole.LAB_MANAGER:
        from sqlalchemy import and_ as sql_and
        subq = db.query(models.EventLog.business_id, models.EventLog.business_type).filter(
            models.EventLog.lab_id == current_user.lab_id
        ).subquery()
        query = query.filter(
            sql_and(
                models.AuditTrail.business_id == subq.c.business_id,
                models.AuditTrail.business_type == subq.c.business_type,
            )
        )

    trails = query.order_by(models.AuditTrail.created_at.asc()).all()

    by_stage: Dict[str, List[float]] = {}
    by_bt: Dict[str, Dict[str, List[float]]] = {}
    total_records = len(trails)

    for t in trails:
        if t.duration_seconds is not None and t.stage_name:
            stage = t.stage_name
            dur = float(t.duration_seconds)
            by_stage.setdefault(stage, [])
            by_stage[stage].append(dur)
            bt = t.business_type.value if hasattr(t.business_type, "value") else str(t.business_type)
            by_bt.setdefault(bt, {})
            by_bt[bt].setdefault(stage, [])
            by_bt[bt][stage].append(dur)

    def _stat(vals: List[float]):
        if not vals:
            return {}
        s = sorted(vals)
        return {
            "count": len(s),
            "avg_seconds": round(sum(s) / len(s), 2),
            "min_seconds": round(s[0], 2),
            "max_seconds": round(s[-1], 2),
            "avg_human": f"{round(sum(s)/len(s)/60, 2)}分钟",
        }

    return {
        "period_days": days,
        "total_audit_records": total_records,
        "stage_overall": {k: _stat(v) for k, v in by_stage.items()},
        "by_business_type": {
            bt: {stage: _stat(vals) for stage, vals in sd.items()}
            for bt, sd in by_bt.items()
        },
    }
