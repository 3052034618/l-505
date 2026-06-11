from datetime import datetime, timedelta
from typing import Optional, Tuple
import models
import schemas
from event_service import event_service
from routers.websocket import dispatch_ws_event
from notification_service import notification_service


# 各环节超时时长（小时）
REMINDER_THRESHOLDS = {
    "usage_supervisor": {"first": 4, "escalate": 8},
    "replenish_lab_manager": {"first": 4, "escalate": 8},
    "replenish_safety": {"first": 4, "escalate": 8},
    "alarm_task": {"first": 2, "escalate": 4},
    "waste_inspection": {"first": 4, "escalate": 8},
}

REMINDER_INTERVAL_HOURS = 4  # 催办发送间隔
MAX_REMINDER_LEVEL = 2  # 0=未催办，1=首次催办，2=已升级


def _hours_since(dt: Optional[datetime]) -> float:
    if not dt:
        return 0
    return (datetime.utcnow() - dt).total_seconds() / 3600.0


def _can_send_again(last_sent_at: Optional[datetime], interval_hours: int = REMINDER_INTERVAL_HOURS) -> bool:
    if not last_sent_at:
        return True
    return (datetime.utcnow() - last_sent_at).total_seconds() >= interval_hours * 3600


def _write_audit_and_event(
    db,
    *,
    business_type: models.EventBusinessType,
    business_id: int,
    business_no: str,
    lab_id: Optional[int],
    stage_name: str,
    from_status: str,
    to_status: str,
    operator_id: int,
    operator_name: str,
    operator_role: str,
    title: str,
    summary: str,
    detail_url: str,
    extra_data: Optional[dict] = None,
    handle_status: models.EventHandleStatus = models.EventHandleStatus.PENDING,
    action: str = "超时催办",
    comment: str = "",
    user_ids: Optional[list] = None,
    roles: Optional[list] = None,
):
    """统一写审计痕迹、事件中心和WS推送"""
    event_service.add_audit_trail(
        db=db,
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
        extra_data=extra_data,
    )
    event_service.log_event(
        db=db,
        business_type=business_type,
        event_type="reminder" if action == "超时催办" else "reminder_escalate",
        business_id=business_id,
        business_no=business_no,
        title=title,
        summary=summary,
        lab_id=lab_id,
        target_user_id=user_ids[0] if user_ids and len(user_ids) == 1 else None,
        handle_status=handle_status,
        detail_url=detail_url,
        extra_data=extra_data,
        emit_ws=False,
    )
    dispatch_ws_event(
        notification_type=business_type.value,
        event="reminder" if action == "超时催办" else "reminder_escalate",
        data={
            "id": business_id,
            "business_no": business_no,
            "business_id": business_id,
            "detail_url": detail_url,
            "title": title,
            "summary": summary,
            "escalated": action != "超时催办",
        },
        user_ids=user_ids,
        lab_id=lab_id,
        roles=roles,
    )


# ========== 领用-导师待审催办 ==========
def process_usage_supervisor_reminders(db) -> Tuple[int, int]:
    cfg = REMINDER_THRESHOLDS["usage_supervisor"]
    pending = db.query(models.UsageRequest).filter(
        models.UsageRequest.status == models.RequestStatus.SUPERVISOR_PENDING
    ).all()

    reminded = 0
    escalated = 0
    for req in pending:
        hours = _hours_since(req.created_at)
        if hours < cfg["first"]:
            continue
        if not _can_send_again(req.last_reminder_sent_at):
            continue

        is_escalate = req.reminder_level >= 1 and hours >= (cfg["first"] + cfg["escalate"])
        is_first = req.reminder_level == 0 and hours >= cfg["first"]

        if not (is_first or is_escalate):
            continue

        roles = []
        user_ids = []
        stage_action = "超时催办"
        comment = f"导师审批超时 {round(hours,1)}h，"
        title_prefix = "【催办】"

        if is_escalate:
            # 升级给主任
            req.reminder_level = 2
            stage_action = "催办升级-转主任"
            title_prefix = "【催办升级】"
            roles = [models.UserRole.LAB_MANAGER, models.UserRole.ADMIN]
            comment += "已升级至实验室主任和管理员"
        else:
            req.reminder_level = 1
            roles = [models.UserRole.SUPERVISOR]
            if req.supervisor_id:
                user_ids = [req.supervisor_id]
            comment += "请导师尽快审批"

        title = f"{title_prefix}领用申请导师审批超时: {req.request_no}"
        summary = f"申请单 {req.request_no}，等待时长 {round(hours,1)} 小时，" + ("请导师尽快处理" if not is_escalate else "已升级至主任")
        detail_url = f"/usage/{req.id}"

        # 找个系统操作员（admin id=1）
        system_operator_name = "系统催办引擎"
        system_operator_role = models.UserRole.ADMIN.value

        _write_audit_and_event(
            db,
            business_type=models.EventBusinessType.USAGE,
            business_id=req.id,
            business_no=req.request_no,
            lab_id=req.lab_id,
            stage_name=stage_action,
            from_status="supervisor_pending",
            to_status="supervisor_pending",
            operator_id=0,
            operator_name=system_operator_name,
            operator_role=system_operator_role,
            title=title,
            summary=summary,
            detail_url=detail_url,
            extra_data={
                "waiting_hours": round(hours, 1),
                "escalated": is_escalate,
                "target_role": "lab_manager" if is_escalate else "supervisor",
            },
            handle_status=models.EventHandleStatus.PENDING,
            action=stage_action,
            comment=comment,
            user_ids=user_ids,
            roles=roles,
        )
        # 也写notification
        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.USAGE_REQUEST,
            title=title,
            content=f"{summary}，请及时处理: {detail_url}",
            user_ids=user_ids,
            roles=roles,
            related_id=req.id,
            related_type="usage",
        )
        req.reminder_sent_count = (req.reminder_sent_count or 0) + 1
        req.last_reminder_sent_at = datetime.utcnow()
        db.flush()
        reminded += 1
        if is_escalate:
            escalated += 1
    return reminded, escalated


# ========== 补货催办（合并主任+安环）==========
def process_replenishment_reminders(db) -> Tuple[int, int]:
    cfg_lab = REMINDER_THRESHOLDS["replenish_lab_manager"]
    cfg_safety = REMINDER_THRESHOLDS["replenish_safety"]

    pending = db.query(models.ReplenishmentRequest).filter(
        models.ReplenishmentRequest.status.in_([
            models.ReplenishmentStatus.PENDING_LAB_MANAGER,
            models.ReplenishmentStatus.PENDING_SAFETY
        ])
    ).all()

    reminded = 0
    escalated = 0
    for req in pending:
        is_safety = req.status == models.ReplenishmentStatus.PENDING_SAFETY
        cfg = cfg_safety if is_safety else cfg_lab
        stage_name_cn = "安环审批" if is_safety else "主任审批"
        role_target = models.UserRole.SAFETY_OFFICER if is_safety else models.UserRole.LAB_MANAGER
        reviewer_id = req.safety_officer_id if is_safety else req.lab_manager_id

        hours = _hours_since(req.created_at)
        if hours < cfg["first"]:
            continue
        if not _can_send_again(req.last_reminder_sent_at):
            continue

        is_escalate = req.reminder_level >= 1 and hours >= (cfg["first"] + cfg["escalate"])
        is_first = req.reminder_level == 0 and hours >= cfg["first"]
        if not (is_first or is_escalate):
            continue

        roles = []
        user_ids = []
        stage_action = f"超时催办-{stage_name_cn}"
        title_prefix = "【催办】"

        if is_escalate:
            req.reminder_level = 2
            stage_action = f"催办升级-{stage_name_cn}→管理员"
            title_prefix = "【催办升级】"
            roles = [models.UserRole.ADMIN]
        else:
            req.reminder_level = 1
            roles = [role_target]
            if reviewer_id:
                user_ids = [reviewer_id]

        title = f"{title_prefix}补货申请{stage_name_cn}超时: {req.request_no}"
        lab_id = None
        chem = db.query(models.Chemical).filter(models.Chemical.id == req.chemical_id).first()
        if chem:
            lab_id = chem.lab_id
        summary = f"补货单 {req.request_no}，等待 {round(hours,1)} 小时"
        detail_url = f"/replenishment/{req.id}"

        _write_audit_and_event(
            db,
            business_type=models.EventBusinessType.REPLENISHMENT,
            business_id=req.id,
            business_no=req.request_no,
            lab_id=lab_id,
            stage_name=stage_action,
            from_status=req.status.value,
            to_status=req.status.value,
            operator_id=0,
            operator_name="系统催办引擎",
            operator_role=models.UserRole.ADMIN.value,
            title=title,
            summary=summary,
            detail_url=detail_url,
            extra_data={
                "waiting_hours": round(hours, 1),
                "escalated": is_escalate,
                "pending_stage": stage_name_cn,
            },
            handle_status=models.EventHandleStatus.PENDING,
            action=stage_action,
            comment=f"{stage_name_cn}超时 {round(hours,1)} 小时",
            user_ids=user_ids,
            roles=roles,
        )
        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.REPLENISHMENT,
            title=title,
            content=f"{summary}，详情 {detail_url}",
            user_ids=user_ids,
            roles=roles,
            related_id=req.id,
            related_type="replenishment",
        )
        req.reminder_sent_count = (req.reminder_sent_count or 0) + 1
        req.last_reminder_sent_at = datetime.utcnow()
        db.flush()
        reminded += 1
        if is_escalate:
            escalated += 1
    return reminded, escalated


# ========== 应急任务催办 ==========
def process_alarm_task_reminders(db) -> Tuple[int, int]:
    cfg = REMINDER_THRESHOLDS["alarm_task"]
    pending = db.query(models.AlarmTask).filter(
        models.AlarmTask.status == models.TaskStatus.ASSIGNED
    ).all()

    reminded = 0
    escalated = 0
    for task in pending:
        hours = _hours_since(task.assigned_at)
        if hours < cfg["first"]:
            continue
        if not _can_send_again(task.last_reminder_sent_at):
            continue

        is_escalate = task.reminder_level >= 1 and hours >= (cfg["first"] + cfg["escalate"])
        is_first = task.reminder_level == 0 and hours >= cfg["first"]
        if not (is_first or is_escalate):
            continue

        roles = []
        user_ids = []
        stage_action = "超时催办-应急任务"
        title_prefix = "【催办】"

        alarm = db.query(models.Alarm).filter(models.Alarm.id == task.alarm_id).first()
        alarm_no = alarm.alarm_no if alarm else f"ALARM#{task.alarm_id}"
        lab_id = alarm.lab_id if alarm else None
        task_desc = (task.task_description or "")[:40]

        if is_escalate:
            task.reminder_level = 2
            stage_action = "催办升级-应急任务→安环+管理员"
            title_prefix = "【催办升级】"
            roles = [models.UserRole.SAFETY_OFFICER, models.UserRole.ADMIN]
        else:
            task.reminder_level = 1
            if task.assignee_id:
                user_ids = [task.assignee_id]
            roles = [models.UserRole.EMERGENCY_TEAM]

        title = f"{title_prefix}应急任务未接单: {alarm_no}"
        summary = f"任务[{task_desc}]待接单 {round(hours,1)} 小时"
        detail_url = f"/alarm-task/{task.id}"

        _write_audit_and_event(
            db,
            business_type=models.EventBusinessType.ALARM,
            business_id=task.alarm_id,
            business_no=alarm_no,
            lab_id=lab_id,
            stage_name=stage_action,
            from_status="assigned",
            to_status="assigned",
            operator_id=0,
            operator_name="系统催办引擎",
            operator_role=models.UserRole.ADMIN.value,
            title=title,
            summary=summary,
            detail_url=f"/alarm/{task.alarm_id}",
            extra_data={
                "task_id": task.id,
                "waiting_hours": round(hours, 1),
                "escalated": is_escalate,
                "assignee_id": task.assignee_id,
            },
            handle_status=models.EventHandleStatus.PENDING,
            action=stage_action,
            comment=summary,
            user_ids=user_ids,
            roles=roles,
        )
        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.ALARM,
            title=title,
            content=f"{summary}，详情 {detail_url}",
            user_ids=user_ids,
            roles=roles,
            related_id=task.alarm_id,
            related_type="alarm",
        )
        task.reminder_sent_count = (task.reminder_sent_count or 0) + 1
        task.last_reminder_sent_at = datetime.utcnow()
        db.flush()
        reminded += 1
        if is_escalate:
            escalated += 1
    return reminded, escalated


# ========== 废液待检查催办 ==========
def process_waste_inspection_reminders(db) -> Tuple[int, int]:
    cfg = REMINDER_THRESHOLDS["waste_inspection"]
    pending = db.query(models.WasteRecord).filter(
        models.WasteRecord.status == models.WasteStatus.PENDING_INSPECTION
    ).all()

    reminded = 0
    escalated = 0
    for w in pending:
        hours = _hours_since(w.created_at)
        if hours < cfg["first"]:
            continue
        if not _can_send_again(w.last_reminder_sent_at):
            continue

        is_escalate = w.reminder_level >= 1 and hours >= (cfg["first"] + cfg["escalate"])
        is_first = w.reminder_level == 0 and hours >= cfg["first"]
        if not (is_first or is_escalate):
            continue

        roles = []
        stage_action = "超时催办-废液检查"
        title_prefix = "【催办】"

        if is_escalate:
            w.reminder_level = 2
            stage_action = "催办升级-废液检查→管理员"
            title_prefix = "【催办升级】"
            roles = [models.UserRole.ADMIN]
        else:
            w.reminder_level = 1
            roles = [models.UserRole.SAFETY_OFFICER]

        title = f"{title_prefix}废液待检查超时: {w.waste_no}"
        chem_name = w.chemical.name if w.chemical else ""
        summary = f"废液 {w.waste_no} ({chem_name} {w.quantity}{w.unit}) 待检查 {round(hours,1)} 小时"
        detail_url = f"/waste/{w.id}"
        user_ids = [w.inspector_id] if w.inspector_id else None

        _write_audit_and_event(
            db,
            business_type=models.EventBusinessType.WASTE,
            business_id=w.id,
            business_no=w.waste_no,
            lab_id=w.lab_id,
            stage_name=stage_action,
            from_status="pending_inspection",
            to_status="pending_inspection",
            operator_id=0,
            operator_name="系统催办引擎",
            operator_role=models.UserRole.ADMIN.value,
            title=title,
            summary=summary,
            detail_url=detail_url,
            extra_data={
                "waiting_hours": round(hours, 1),
                "escalated": is_escalate,
            },
            handle_status=models.EventHandleStatus.PENDING,
            action=stage_action,
            comment=summary,
            user_ids=user_ids,
            roles=roles,
        )
        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.WASTE,
            title=title,
            content=f"{summary}，详情 {detail_url}",
            user_ids=user_ids,
            roles=roles,
            related_id=w.id,
            related_type="waste",
        )
        w.reminder_sent_count = (w.reminder_sent_count or 0) + 1
        w.last_reminder_sent_at = datetime.utcnow()
        db.flush()
        reminded += 1
        if is_escalate:
            escalated += 1
    return reminded, escalated


def process_all_reminders(db) -> dict:
    """处理全部催办（定时任务入口）"""
    total_reminded = 0
    total_escalated = 0
    results = {}

    for name, fn in [
        ("usage_supervisor", process_usage_supervisor_reminders),
        ("replenishment", process_replenishment_reminders),
        ("alarm_task", process_alarm_task_reminders),
        ("waste_inspection", process_waste_inspection_reminders),
    ]:
        try:
            r, e = fn(db)
            results[name] = {"reminded": r, "escalated": e}
            total_reminded += r
            total_escalated += e
        except Exception as ex:
            results[name] = {"error": str(ex)}

    if total_reminded > 0:
        db.commit()

    return {
        "total_reminded": total_reminded,
        "total_escalated": total_escalated,
        "detail": results,
        "processed_at": datetime.utcnow().isoformat(),
    }
