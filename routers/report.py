from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, date, timedelta
from io import BytesIO
import json
from database import get_db
from auth import get_current_user, require_roles
import models
import schemas

router_report = APIRouter(prefix="/api/reports", tags=["日报统计"])
router_notification = APIRouter(prefix="/api/notifications", tags=["通知中心"])


def generate_daily_report_for_lab(db: Session, lab_id: Optional[int], report_date: date) -> models.DailyReport:
    start_of_day = datetime.combine(report_date, datetime.min.time())
    end_of_day = datetime.combine(report_date + timedelta(days=1), datetime.min.time())

    inventory_query = db.query(models.Inventory)
    if lab_id:
        inventory_query = inventory_query.join(models.StorageCabinet).filter(
            models.StorageCabinet.lab_id == lab_id
        )
    all_inventory = inventory_query.all()

    chemical_ids = set(inv.chemical_id for inv in all_inventory)
    total_chemical_types = len(chemical_ids)
    total_inventory_quantity = sum(inv.current_quantity for inv in all_inventory)

    consumption_by_category = {}
    usage_query = db.query(models.UsageRequest).filter(
        models.UsageRequest.status.in_([
            models.RequestStatus.AUTO_APPROVED,
            models.RequestStatus.SUPERVISOR_APPROVED,
            models.RequestStatus.COMPLETED
        ]),
        models.UsageRequest.created_at >= start_of_day,
        models.UsageRequest.created_at < end_of_day
    )
    if lab_id:
        usage_query = usage_query.filter(models.UsageRequest.lab_id == lab_id)
    usages = usage_query.all()

    for u in usages:
        chemical = u.chemical
        if not chemical:
            continue
        cat = chemical.category.value if hasattr(chemical.category, 'value') else str(chemical.category)
        if cat not in consumption_by_category:
            consumption_by_category[cat] = {"quantity": 0, "count": 0, "chemicals": []}
        consumption_by_category[cat]["quantity"] += u.actual_quantity or u.requested_quantity
        consumption_by_category[cat]["count"] += 1
        name_entry = f"{chemical.name} ({u.actual_quantity or u.requested_quantity}{u.unit})"
        if name_entry not in consumption_by_category[cat]["chemicals"]:
            consumption_by_category[cat]["chemicals"].append(name_entry)

    usage_request_count = len(usages)

    storage_status = {
        "total_items": len(all_inventory),
        "normal": 0,
        "low_stock": 0,
        "expiring_soon": 0,
        "expired": 0,
        "by_cabinet": {}
    }
    today = date.today()
    for inv in all_inventory:
        if inv.current_quantity <= inv.safety_level:
            storage_status["low_stock"] += 1
        if inv.expiry_date:
            if inv.expiry_date < today:
                storage_status["expired"] += 1
            elif (inv.expiry_date - today).days <= 30:
                storage_status["expiring_soon"] += 1
        else:
            storage_status["normal"] += 1

        cabinet_key = inv.cabinet.cabinet_no if inv.cabinet else "unknown"
        if cabinet_key not in storage_status["by_cabinet"]:
            storage_status["by_cabinet"][cabinet_key] = {"items": 0, "quantity": 0}
        storage_status["by_cabinet"][cabinet_key]["items"] += 1
        storage_status["by_cabinet"][cabinet_key]["quantity"] += inv.current_quantity

    alarm_query = db.query(models.Alarm).filter(
        models.Alarm.triggered_at >= start_of_day,
        models.Alarm.triggered_at < end_of_day
    )
    if lab_id:
        alarm_query = alarm_query.filter(models.Alarm.lab_id == lab_id)
    alarms = alarm_query.all()

    alarm_count_by_level = {"info": 0, "warning": 0, "critical": 0, "emergency": 0}
    for a in alarms:
        lvl = a.level.value if hasattr(a.level, 'value') else str(a.level)
        alarm_count_by_level[lvl] = alarm_count_by_level.get(lvl, 0) + 1

    safety_incidents = []
    for a in alarms:
        if a.level in [models.AlarmLevel.CRITICAL, models.AlarmLevel.EMERGENCY]:
            safety_incidents.append({
                "alarm_no": a.alarm_no,
                "level": a.level.value if hasattr(a.level, 'value') else str(a.level),
                "type": a.type,
                "description": a.description,
                "status": a.status.value if hasattr(a.status, 'value') else str(a.status),
                "triggered_at": a.triggered_at.isoformat(),
                "resolution": a.resolution_notes
            })

    inbound_query = db.query(models.InboundRecord).filter(
        models.InboundRecord.created_at >= start_of_day,
        models.InboundRecord.created_at < end_of_day
    )
    if lab_id:
        inbound_query = inbound_query.join(models.Chemical).filter(models.Chemical.lab_id == lab_id)
    inbound_count = inbound_query.count()

    waste_query = db.query(models.WasteRecord).filter(
        models.WasteRecord.created_at >= start_of_day,
        models.WasteRecord.created_at < end_of_day
    )
    if lab_id:
        waste_query = waste_query.filter(models.WasteRecord.lab_id == lab_id)
    waste_count = waste_query.count()

    rep_query = db.query(models.ReplenishmentRequest).filter(
        models.ReplenishmentRequest.created_at >= start_of_day,
        models.ReplenishmentRequest.created_at < end_of_day
    )
    replenishment_count = rep_query.count()

    existing = db.query(models.DailyReport).filter(
        models.DailyReport.report_date == report_date,
        models.DailyReport.lab_id == lab_id
    ).first()

    if existing:
        existing.total_chemical_types = total_chemical_types
        existing.total_inventory_quantity = total_inventory_quantity
        existing.consumption_by_category = consumption_by_category
        existing.storage_status_summary = storage_status
        existing.alarm_count_by_level = alarm_count_by_level
        existing.alarm_count_total = len(alarms)
        existing.usage_request_count = usage_request_count
        existing.inbound_count = inbound_count
        existing.waste_count = waste_count
        existing.replenishment_count = replenishment_count
        existing.safety_incidents = safety_incidents
        existing.generated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    report = models.DailyReport(
        report_date=report_date,
        lab_id=lab_id,
        total_chemical_types=total_chemical_types,
        total_inventory_quantity=total_inventory_quantity,
        consumption_by_category=consumption_by_category,
        storage_status_summary=storage_status,
        alarm_count_by_level=alarm_count_by_level,
        alarm_count_total=len(alarms),
        usage_request_count=usage_request_count,
        inbound_count=inbound_count,
        waste_count=waste_count,
        replenishment_count=replenishment_count,
        safety_incidents=safety_incidents,
        generated_at=datetime.utcnow()
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def generate_all_daily_reports(db: Session, report_date: Optional[date] = None) -> List[models.DailyReport]:
    if not report_date:
        report_date = date.today() - timedelta(days=1)

    labs = db.query(models.Laboratory).filter(models.Laboratory.is_active == True).all()
    reports = []

    overall = generate_daily_report_for_lab(db, None, report_date)
    reports.append(overall)

    for lab in labs:
        r = generate_daily_report_for_lab(db, lab.id, report_date)
        reports.append(r)

    return reports


@router_report.post("/generate")
def trigger_daily_report_generation(
    report_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER, models.UserRole.LAB_MANAGER))
):
    reports = generate_all_daily_reports(db, report_date)
    return {
        "generated_count": len(reports),
        "report_date": str(report_date or (date.today() - timedelta(days=1))),
        "reports": [
            {"id": r.id, "lab_id": r.lab_id, "report_date": str(r.report_date)}
            for r in reports
        ]
    }


@router_report.get("", response_model=List[schemas.DailyReportResponse])
def list_daily_reports(
    report_date: Optional[date] = None,
    lab_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.DailyReport)
    if report_date:
        query = query.filter(models.DailyReport.report_date == report_date)
    if lab_id:
        query = query.filter(models.DailyReport.lab_id == lab_id)
    if start_date:
        query = query.filter(models.DailyReport.report_date >= start_date)
    if end_date:
        query = query.filter(models.DailyReport.report_date <= end_date)

    reports = query.order_by(models.DailyReport.report_date.desc(), models.DailyReport.lab_id.asc()).offset(skip).limit(limit).all()

    return [
        schemas.DailyReportResponse(
            id=r.id,
            report_date=r.report_date,
            lab_id=r.lab_id,
            lab_name=r.lab.name if r.lab else (None if r.lab_id else "全平台汇总"),
            total_chemical_types=r.total_chemical_types,
            total_inventory_quantity=r.total_inventory_quantity,
            consumption_by_category=r.consumption_by_category,
            storage_status_summary=r.storage_status_summary,
            alarm_count_by_level=r.alarm_count_by_level,
            alarm_count_total=r.alarm_count_total,
            usage_request_count=r.usage_request_count,
            inbound_count=r.inbound_count,
            waste_count=r.waste_count,
            replenishment_count=r.replenishment_count,
            safety_incidents=r.safety_incidents,
            generated_at=r.generated_at
        ) for r in reports
    ]


@router_report.get("/{report_id}", response_model=schemas.DailyReportResponse)
def get_daily_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    r = db.query(models.DailyReport).filter(models.DailyReport.id == report_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="日报不存在")

    return schemas.DailyReportResponse(
        id=r.id,
        report_date=r.report_date,
        lab_id=r.lab_id,
        lab_name=r.lab.name if r.lab else (None if r.lab_id else "全平台汇总"),
        total_chemical_types=r.total_chemical_types,
        total_inventory_quantity=r.total_inventory_quantity,
        consumption_by_category=r.consumption_by_category,
        storage_status_summary=r.storage_status_summary,
        alarm_count_by_level=r.alarm_count_by_level,
        alarm_count_total=r.alarm_count_total,
        usage_request_count=r.usage_request_count,
        inbound_count=r.inbound_count,
        waste_count=r.waste_count,
        replenishment_count=r.replenishment_count,
        safety_incidents=r.safety_incidents,
        generated_at=r.generated_at
    )


@router_report.get("/export/xlsx")
def export_daily_reports_xlsx(
    report_date: Optional[date] = None,
    lab_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    try:
        import pandas as pd
        from openpyxl import Workbook
    except ImportError:
        return export_daily_reports_json(report_date, lab_id, start_date, end_date, db, current_user)

    query = db.query(models.DailyReport)
    if report_date:
        query = query.filter(models.DailyReport.report_date == report_date)
    if lab_id:
        query = query.filter(models.DailyReport.lab_id == lab_id)
    if start_date:
        query = query.filter(models.DailyReport.report_date >= start_date)
    if end_date:
        query = query.filter(models.DailyReport.report_date <= end_date)
    reports = query.order_by(models.DailyReport.report_date.desc()).all()

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        summary_data = []
        for r in reports:
            lab_name = r.lab.name if r.lab else (None if r.lab_id else "全平台汇总")
            summary_data.append({
                "日期": str(r.report_date),
                "实验室": lab_name or "",
                "化学品种类数": r.total_chemical_types,
                "库存总量": r.total_inventory_quantity,
                "领用申请数": r.usage_request_count,
                "入库数": r.inbound_count,
                "废液记录数": r.waste_count,
                "补货申请数": r.replenishment_count,
                "告警总数": r.alarm_count_total,
                "INFO告警": (r.alarm_count_by_level or {}).get("info", 0),
                "WARNING告警": (r.alarm_count_by_level or {}).get("warning", 0),
                "CRITICAL告警": (r.alarm_count_by_level or {}).get("critical", 0),
                "EMERGENCY告警": (r.alarm_count_by_level or {}).get("emergency", 0),
            })
        pd.DataFrame(summary_data).to_excel(writer, sheet_name="汇总", index=False)

        consumption_rows = []
        for r in reports:
            lab_name = r.lab.name if r.lab else (None if r.lab_id else "全平台汇总")
            if r.consumption_by_category:
                for cat, data in r.consumption_by_category.items():
                    consumption_rows.append({
                        "日期": str(r.report_date),
                        "实验室": lab_name or "",
                        "类别": cat,
                        "消耗量": data.get("quantity", 0),
                        "申请次数": data.get("count", 0),
                        "涉及化学品": ", ".join(data.get("chemicals", []))
                    })
        if consumption_rows:
            pd.DataFrame(consumption_rows).to_excel(writer, sheet_name="分类消耗", index=False)

        incident_rows = []
        for r in reports:
            lab_name = r.lab.name if r.lab else (None if r.lab_id else "全平台汇总")
            if r.safety_incidents:
                for inc in r.safety_incidents:
                    incident_rows.append({
                        "日期": str(r.report_date),
                        "实验室": lab_name or "",
                        "告警编号": inc.get("alarm_no", ""),
                        "等级": inc.get("level", ""),
                        "类型": inc.get("type", ""),
                        "描述": inc.get("description", ""),
                        "状态": inc.get("status", ""),
                        "触发时间": inc.get("triggered_at", ""),
                        "处置": inc.get("resolution", "")
                    })
        if incident_rows:
            pd.DataFrame(incident_rows).to_excel(writer, sheet_name="安全事件", index=False)

    output.seek(0)
    filename = f"daily_report_{report_date or 'range'}.xlsx"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers
    )


@router_report.get("/export/json")
def export_daily_reports_json(
    report_date: Optional[date] = None,
    lab_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.DailyReport)
    if report_date:
        query = query.filter(models.DailyReport.report_date == report_date)
    if lab_id:
        query = query.filter(models.DailyReport.lab_id == lab_id)
    if start_date:
        query = query.filter(models.DailyReport.report_date >= start_date)
    if end_date:
        query = query.filter(models.DailyReport.report_date <= end_date)
    reports = query.order_by(models.DailyReport.report_date.desc()).all()

    summary_data = []
    for r in reports:
        lab_name = r.lab.name if r.lab else (None if r.lab_id else "全平台汇总")
        summary_data.append({
            "日期": str(r.report_date),
            "实验室": lab_name or "",
            "化学品种类数": r.total_chemical_types,
            "库存总量": r.total_inventory_quantity,
            "领用申请数": r.usage_request_count,
            "入库数": r.inbound_count,
            "废液记录数": r.waste_count,
            "补货申请数": r.replenishment_count,
            "告警总数": r.alarm_count_total,
            "告警分级": r.alarm_count_by_level or {},
            "分类消耗": r.consumption_by_category or {},
            "库存状态": r.storage_status_summary or {},
            "安全事件": r.safety_incidents or []
        })

    output = BytesIO()
    output.write(json.dumps({"reports": summary_data, "count": len(summary_data)}, ensure_ascii=False, indent=2, default=str).encode("utf-8"))
    output.seek(0)
    filename = f"daily_report_{report_date or 'range'}.json"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(
        output,
        media_type="application/json; charset=utf-8",
        headers=headers
    )


@router_report.get("/export/csv")
def export_daily_reports_csv(
    report_date: Optional[date] = None,
    lab_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    import csv
    query = db.query(models.DailyReport)
    if report_date:
        query = query.filter(models.DailyReport.report_date == report_date)
    if lab_id:
        query = query.filter(models.DailyReport.lab_id == lab_id)
    reports = query.order_by(models.DailyReport.report_date.desc()).all()

    output = BytesIO()
    output.write(b'\xef\xbb\xbf')
    import io
    text_wrapper = io.TextIOWrapper(output, encoding='utf-8', write_through=True)
    writer = csv.writer(text_wrapper)

    headers = ["日期", "实验室", "化学品种类数", "库存总量", "领用申请数", "入库数", "废液记录数", "补货申请数", "告警总数"]
    writer.writerow(headers)

    for r in reports:
        lab_name = r.lab.name if r.lab else (None if r.lab_id else "全平台汇总")
        writer.writerow([
            str(r.report_date),
            lab_name or "",
            r.total_chemical_types,
            r.total_inventory_quantity,
            r.usage_request_count,
            r.inbound_count,
            r.waste_count,
            r.replenishment_count,
            r.alarm_count_total
        ])

    output.seek(0)
    filename = f"daily_report_{report_date or 'all'}.csv"
    response_headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(
        output,
        media_type="text/csv; charset=utf-8",
        headers=response_headers
    )


@router_notification.get("", response_model=List[schemas.NotificationResponse])
def get_my_notifications(
    unread_only: bool = False,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    from notification_service import notification_service
    notifications = notification_service.get_user_notifications(
        db, current_user.id, skip, limit, unread_only
    )
    return [
        schemas.NotificationResponse(
            id=n.id,
            type=n.type,
            title=n.title,
            content=n.content,
            user_id=n.user_id,
            lab_id=n.lab_id,
            related_id=n.related_id,
            related_type=n.related_type,
            is_read=n.is_read,
            created_at=n.created_at
        ) for n in notifications
    ]


@router_notification.get("/unread-count")
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    count = db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
        models.Notification.is_read == False
    ).count()
    return {"unread_count": count}


@router_notification.post("/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    from notification_service import notification_service
    success = notification_service.mark_as_read(db, notification_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="通知不存在")
    return {"success": True}


@router_notification.post("/read-all")
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    from notification_service import notification_service
    count = notification_service.mark_all_as_read(db, current_user.id)
    return {"marked_count": count}
