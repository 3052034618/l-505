from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
import models
from auth import generate_request_no
from routers.websocket import dispatch_ws_event


def log_event(
    db: Session,
    business_type: models.EventBusinessType,
    event_type: str,
    business_id: int,
    business_no: str,
    title: str,
    summary: Optional[str] = None,
    lab_id: Optional[int] = None,
    operator_id: Optional[int] = None,
    target_role: Optional[str] = None,
    target_user_id: Optional[int] = None,
    handle_status: models.EventHandleStatus = models.EventHandleStatus.PENDING,
    detail_url: Optional[str] = None,
    extra_data: Optional[Dict[str, Any]] = None,
    emit_ws: bool = True,
    ws_user_ids: Optional[List[int]] = None,
    ws_lab_id: Optional[int] = None,
    ws_roles: Optional[List] = None,
) -> models.EventLog:
    event = models.EventLog(
        event_no=generate_request_no("EV"),
        business_type=business_type,
        event_type=event_type,
        business_id=business_id,
        business_no=business_no,
        lab_id=lab_id,
        operator_id=operator_id,
        target_role=target_role,
        target_user_id=target_user_id,
        title=title,
        summary=summary,
        handle_status=handle_status,
        detail_url=detail_url,
        extra_data=extra_data,
        created_at=datetime.utcnow(),
    )
    db.add(event)
    db.flush()

    if emit_ws:
        notify_data = {
            "event_id": event.id,
            "event_no": event.event_no,
            "business_type": business_type.value if hasattr(business_type, "value") else str(business_type),
            "event_type": event_type,
            "business_id": business_id,
            "business_no": business_no,
            "title": title,
            "summary": summary,
            "detail_url": detail_url,
            "handle_status": handle_status.value if hasattr(handle_status, "value") else str(handle_status),
            "created_at": event.created_at.isoformat(),
        }
        if extra_data:
            notify_data.update(extra_data)
        dispatch_ws_event(
            notification_type="event",
            event=event_type,
            data=notify_data,
            user_ids=ws_user_ids,
            lab_id=ws_lab_id,
            roles=ws_roles,
        )
    return event


def add_audit_trail(
    db: Session,
    business_type: models.EventBusinessType,
    business_id: int,
    business_no: Optional[str],
    action: str,
    stage_name: Optional[str] = None,
    from_status: Optional[str] = None,
    to_status: Optional[str] = None,
    operator_id: Optional[int] = None,
    operator_name: Optional[str] = None,
    operator_role: Optional[str] = None,
    comment: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    extra_data: Optional[Dict[str, Any]] = None,
) -> models.AuditTrail:
    trail = models.AuditTrail(
        business_type=business_type,
        business_id=business_id,
        business_no=business_no,
        action=action,
        stage_name=stage_name,
        from_status=from_status,
        to_status=to_status,
        operator_id=operator_id,
        operator_name=operator_name,
        operator_role=operator_role,
        comment=comment,
        duration_seconds=duration_seconds,
        extra_data=extra_data,
        created_at=datetime.utcnow(),
    )
    db.add(trail)
    db.flush()
    return trail


def get_audit_trails(
    db: Session,
    business_type: models.EventBusinessType,
    business_id: int,
) -> List[models.AuditTrail]:
    return (
        db.query(models.AuditTrail)
        .filter(
            models.AuditTrail.business_type == business_type,
            models.AuditTrail.business_id == business_id,
        )
        .order_by(models.AuditTrail.created_at.asc())
        .all()
    )


def mark_event_completed(
    db: Session,
    event_id: int,
) -> Optional[models.EventLog]:
    ev = db.query(models.EventLog).filter(models.EventLog.id == event_id).first()
    if ev:
        ev.handle_status = models.EventHandleStatus.COMPLETED
        db.flush()
    return ev


def mark_event_handling(
    db: Session,
    event_id: int,
) -> Optional[models.EventLog]:
    ev = db.query(models.EventLog).filter(models.EventLog.id == event_id).first()
    if ev:
        ev.handle_status = models.EventHandleStatus.HANDLING
        db.flush()
    return ev


def update_event_handle_status(
    db: Session,
    business_type: models.EventBusinessType,
    business_id: int,
    new_handle_status: models.EventHandleStatus,
    extra_update: Optional[Dict[str, Any]] = None,
) -> Optional[models.EventLog]:
    ev = db.query(models.EventLog).filter(
        models.EventLog.business_type == business_type,
        models.EventLog.business_id == business_id,
    ).order_by(models.EventLog.id.desc()).first()
    if ev:
        ev.handle_status = new_handle_status
        if extra_update:
            for k, v in extra_update.items():
                if hasattr(ev, k) and v is not None:
                    setattr(ev, k, v)
        db.flush()
    return ev


class EventService:
    log_event = staticmethod(log_event)
    add_audit_trail = staticmethod(add_audit_trail)
    get_audit_trails = staticmethod(get_audit_trails)
    mark_completed = staticmethod(mark_event_completed)
    mark_handling = staticmethod(mark_event_handling)
    update_event_handle_status = staticmethod(update_event_handle_status)


event_service = EventService()
