from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
from database import get_db
from auth import get_current_user, require_roles, generate_request_no
from notification_service import notification_service
from routers.websocket import dispatch_ws_event
import models
import schemas

router_waste = APIRouter(prefix="/api/waste", tags=["废液回收"])
router_replenishment = APIRouter(prefix="/api/replenishment", tags=["库存补货"])


import json as _json

def _parse_waste_types_list(val):
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x) for x in val]
    if isinstance(val, str):
        try:
            parsed = _json.loads(val)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
            return [str(val)]
        except Exception:
            return [str(val)]
    return []


def find_matching_disposal_center(db: Session, waste_type: str) -> Optional[models.DisposalCenter]:
    centers = db.query(models.DisposalCenter).filter(models.DisposalCenter.is_active == True).all()
    for center in centers:
        allowed = _parse_waste_types_list(center.allowed_waste_types)
        if not allowed or waste_type in allowed:
            return center
    return None


def auto_create_batch_for_waste(db: Session, waste: models.WasteRecord, operator_id: int) -> Optional[models.WasteBatch]:
    if waste.status != models.WasteStatus.INSPECTION_PASSED:
        return None
    if waste.batch_id is not None:
        return None

    center = find_matching_disposal_center(db, waste.waste_type)
    if not center:
        return None

    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    existing_batch = db.query(models.WasteBatch).filter(
        models.WasteBatch.disposal_center_id == center.id,
        models.WasteBatch.status == "created",
        models.WasteBatch.created_at >= one_hour_ago
    ).first()

    if existing_batch:
        waste.batch_id = existing_batch.id
        waste.disposal_center_id = center.id
        waste.status = models.WasteStatus.BATCHED
        existing_batch.total_quantity = (existing_batch.total_quantity or 0) + waste.quantity
        return existing_batch

    batch_no = generate_request_no("WB")
    batch = models.WasteBatch(
        batch_no=batch_no,
        disposal_center_id=center.id,
        transport_company="系统自动调度",
        total_quantity=waste.quantity,
        status="created",
        created_by_id=operator_id,
        created_at=datetime.utcnow()
    )
    db.add(batch)
    db.flush()

    waste.batch_id = batch.id
    waste.disposal_center_id = center.id
    waste.status = models.WasteStatus.BATCHED
    return batch


def inspect_container_and_label(waste_record: models.WasteRecord, inspection: schemas.WasteInspectionResult, db: Session):
    waste_record.seal_inspection_passed = inspection.seal_passed
    waste_record.seal_inspection_notes = inspection.seal_notes
    waste_record.label_inspection_passed = inspection.label_passed
    waste_record.label_inspection_notes = inspection.label_notes
    waste_record.violation_recorded = inspection.violation_recorded
    waste_record.violation_type = inspection.violation_type
    waste_record.violation_notes = inspection.violation_notes
    waste_record.inspected_at = datetime.utcnow()

    if inspection.seal_passed and inspection.label_passed:
        waste_record.status = models.WasteStatus.INSPECTION_PASSED
        return True
    else:
        waste_record.status = models.WasteStatus.INSPECTION_FAILED
        return False


@router_waste.post("", response_model=schemas.WasteRecordResponse)
def create_waste_record(
    waste_in: schemas.WasteRecordCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    chemical = db.query(models.Chemical).filter(models.Chemical.id == waste_in.chemical_id).first()
    if not chemical:
        raise HTTPException(status_code=404, detail="化学品不存在")

    waste_no = generate_request_no("WS")
    record = models.WasteRecord(
        waste_no=waste_no,
        chemical_id=waste_in.chemical_id,
        lab_id=waste_in.lab_id or current_user.lab_id,
        waste_type=waste_in.waste_type or chemical.category.value,
        quantity=waste_in.quantity,
        unit=waste_in.unit,
        container_no=waste_in.container_no,
        container_type=waste_in.container_type,
        status=models.WasteStatus.PENDING_INSPECTION,
        submitter_id=current_user.id,
        created_at=datetime.utcnow()
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    notification_service.create_notification(
        db=db,
        notification_type=models.NotificationType.WASTE,
        title=f"废液回收待检查: {chemical.name}",
        content=f"废液编号: {waste_no}, 数量: {waste_in.quantity}{waste_in.unit}, 容器: {waste_in.container_no or '未指定'}",
        roles=[models.UserRole.SAFETY_OFFICER],
        lab_id=record.lab_id,
        related_id=record.id,
        related_type="waste"
    )

    return schemas.WasteRecordResponse(
        id=record.id,
        waste_no=record.waste_no,
        chemical_id=record.chemical_id,
        chemical_name=chemical.name,
        lab_id=record.lab_id,
        waste_type=record.waste_type,
        quantity=record.quantity,
        unit=record.unit,
        container_no=record.container_no,
        container_type=record.container_type,
        seal_inspection_passed=record.seal_inspection_passed,
        seal_inspection_notes=record.seal_inspection_notes,
        label_inspection_passed=record.label_inspection_passed,
        label_inspection_notes=record.label_inspection_notes,
        violation_recorded=record.violation_recorded,
        violation_type=record.violation_type,
        violation_notes=record.violation_notes,
        status=record.status,
        batch_id=record.batch_id,
        disposal_center_id=record.disposal_center_id,
        created_at=record.created_at,
        inspected_at=record.inspected_at
    )


@router_waste.post("/{waste_id}/inspect", response_model=schemas.WasteRecordResponse)
def inspect_waste(
    waste_id: int,
    inspection_in: schemas.WasteInspectionRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(models.UserRole.SAFETY_OFFICER, models.UserRole.ADMIN))
):
    waste = db.query(models.WasteRecord).filter(models.WasteRecord.id == waste_id).first()
    if not waste:
        raise HTTPException(status_code=404, detail="废液记录不存在")
    if waste.status != models.WasteStatus.PENDING_INSPECTION:
        raise HTTPException(status_code=400, detail="当前状态不可检查")

    inspection = inspection_in.inspection_result
    passed = inspect_container_and_label(waste, inspection, db)
    waste.inspector_id = current_user.id

    created_batch = None
    if passed:
        created_batch = auto_create_batch_for_waste(db, waste, current_user.id)

    db.commit()
    db.refresh(waste)

    if passed:
        batch_msg = f", 转运批次: {created_batch.batch_no}" if created_batch else ", 暂无匹配处理中心，等待调度"
        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.WASTE,
            title=f"废液检查通过，待转运",
            content=f"废液编号: {waste.waste_no}, 化学品: {waste.chemical.name if waste.chemical else ''}{batch_msg}",
            user_ids=[waste.submitter_id],
            roles=[models.UserRole.SAFETY_OFFICER],
            related_id=waste.id,
            related_type="waste"
        )
        dispatch_ws_event(
            notification_type="waste",
            event="inspection_passed",
            data={
                "id": waste.id,
                "waste_no": waste.waste_no,
                "chemical_id": waste.chemical_id,
                "chemical_name": waste.chemical.name if waste.chemical else None,
                "lab_id": waste.lab_id,
                "waste_type": waste.waste_type,
                "quantity": waste.quantity,
                "unit": waste.unit,
                "batch_id": waste.batch_id,
                "batch_no": created_batch.batch_no if created_batch else None,
                "disposal_center_id": waste.disposal_center_id,
                "status": "inspection_passed"
            },
            user_ids=[waste.submitter_id, current_user.id],
            lab_id=waste.lab_id,
            roles=[models.UserRole.SAFETY_OFFICER, models.UserRole.LAB_MANAGER]
        )
    else:
        reasons = []
        if not inspection.seal_passed:
            reasons.append(f"密封性不合格: {inspection.seal_notes or '未说明'}")
        if not inspection.label_passed:
            reasons.append(f"标签不合格: {inspection.label_notes or '未说明'}")
        if inspection.violation_recorded:
            reasons.append(f"违规记录: {inspection.violation_type} - {inspection.violation_notes or ''}")

        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.WASTE,
            title=f"废液检查被退回",
            content=f"废液编号: {waste.waste_no}, 原因: {' | '.join(reasons)}",
            user_ids=[waste.submitter_id],
            related_id=waste.id,
            related_type="waste"
        )
        dispatch_ws_event(
            notification_type="waste",
            event="inspection_failed",
            data={
                "id": waste.id,
                "waste_no": waste.waste_no,
                "chemical_id": waste.chemical_id,
                "chemical_name": waste.chemical.name if waste.chemical else None,
                "lab_id": waste.lab_id,
                "waste_type": waste.waste_type,
                "quantity": waste.quantity,
                "unit": waste.unit,
                "reject_reasons": reasons,
                "seal_passed": inspection.seal_passed,
                "label_passed": inspection.label_passed,
                "violation_recorded": inspection.violation_recorded,
                "violation_type": inspection.violation_type,
                "status": "inspection_failed"
            },
            user_ids=[waste.submitter_id, current_user.id],
            lab_id=waste.lab_id,
            roles=[models.UserRole.SAFETY_OFFICER, models.UserRole.LAB_MANAGER]
        )

    chemical = waste.chemical
    return schemas.WasteRecordResponse(
        id=waste.id,
        waste_no=waste.waste_no,
        chemical_id=waste.chemical_id,
        chemical_name=chemical.name if chemical else None,
        lab_id=waste.lab_id,
        waste_type=waste.waste_type,
        quantity=waste.quantity,
        unit=waste.unit,
        container_no=waste.container_no,
        container_type=waste.container_type,
        seal_inspection_passed=waste.seal_inspection_passed,
        seal_inspection_notes=waste.seal_inspection_notes,
        label_inspection_passed=waste.label_inspection_passed,
        label_inspection_notes=waste.label_inspection_notes,
        violation_recorded=waste.violation_recorded,
        violation_type=waste.violation_type,
        violation_notes=waste.violation_notes,
        status=waste.status,
        batch_id=waste.batch_id,
        disposal_center_id=waste.disposal_center_id,
        created_at=waste.created_at,
        inspected_at=waste.inspected_at
    )


@router_waste.post("/batches", response_model=schemas.WasteBatchResponse)
def create_waste_batch(
    batch_in: schemas.WasteBatchCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(models.UserRole.SAFETY_OFFICER, models.UserRole.ADMIN))
):
    center = db.query(models.DisposalCenter).filter(models.DisposalCenter.id == batch_in.disposal_center_id).first()
    if not center:
        raise HTTPException(status_code=404, detail="处理中心不存在")

    waste_records = db.query(models.WasteRecord).filter(
        models.WasteRecord.id.in_(batch_in.waste_record_ids),
        models.WasteRecord.status == models.WasteStatus.INSPECTION_PASSED
    ).all()

    if not waste_records:
        raise HTTPException(status_code=400, detail="没有合格的待转运废液记录")

    if len(waste_records) != len(batch_in.waste_record_ids):
        invalid_ids = set(batch_in.waste_record_ids) - {w.id for w in waste_records}
        raise HTTPException(status_code=400, detail=f"部分记录状态不合格: {list(invalid_ids)}")

    for w in waste_records:
        if center.allowed_waste_types and w.waste_type and w.waste_type not in center.allowed_waste_types:
            raise HTTPException(status_code=400, detail=f"处理中心不接受类型为 {w.waste_type} 的废液 (ID={w.id})")

    batch_no = generate_request_no("WB")
    total_quantity = sum(w.quantity for w in waste_records)

    batch = models.WasteBatch(
        batch_no=batch_no,
        disposal_center_id=batch_in.disposal_center_id,
        transport_company=batch_in.transport_company,
        driver_name=batch_in.driver_name,
        vehicle_plate=batch_in.vehicle_plate,
        manifest_no=batch_in.manifest_no,
        total_quantity=total_quantity,
        status="created",
        created_by_id=current_user.id,
        created_at=datetime.utcnow()
    )
    db.add(batch)
    db.flush()

    for w in waste_records:
        w.batch_id = batch.id
        w.disposal_center_id = batch_in.disposal_center_id
        w.status = models.WasteStatus.BATCHED

    db.commit()
    db.refresh(batch)

    notification_service.create_notification(
        db=db,
        notification_type=models.NotificationType.WASTE,
        title=f"转运批次已生成: {batch_no}",
        content=f"共{len(waste_records)}条记录，总量: {total_quantity}, 处理中心: {center.name}",
        roles=[models.UserRole.SAFETY_OFFICER, models.UserRole.ADMIN],
        related_id=batch.id,
        related_type="waste_batch"
    )

    return schemas.WasteBatchResponse(
        id=batch.id,
        batch_no=batch.batch_no,
        disposal_center_id=batch.disposal_center_id,
        transport_company=batch.transport_company,
        driver_name=batch.driver_name,
        vehicle_plate=batch.vehicle_plate,
        manifest_no=batch.manifest_no,
        total_quantity=batch.total_quantity,
        status=batch.status,
        created_at=batch.created_at,
        shipped_at=batch.shipped_at,
        received_at=batch.received_at,
        waste_records=[
            schemas.WasteRecordResponse(
                id=w.id,
                waste_no=w.waste_no,
                chemical_id=w.chemical_id,
                chemical_name=w.chemical.name if w.chemical else None,
                lab_id=w.lab_id,
                waste_type=w.waste_type,
                quantity=w.quantity,
                unit=w.unit,
                container_no=w.container_no,
                container_type=w.container_type,
                seal_inspection_passed=w.seal_inspection_passed,
                seal_inspection_notes=w.seal_inspection_notes,
                label_inspection_passed=w.label_inspection_passed,
                label_inspection_notes=w.label_inspection_notes,
                violation_recorded=w.violation_recorded,
                violation_type=w.violation_type,
                violation_notes=w.violation_notes,
                status=w.status,
                batch_id=w.batch_id,
                disposal_center_id=w.disposal_center_id,
                created_at=w.created_at,
                inspected_at=w.inspected_at
            ) for w in waste_records
        ]
    )


@router_waste.get("", response_model=List[schemas.WasteRecordResponse])
def list_waste_records(
    status: Optional[str] = None,
    lab_id: Optional[int] = None,
    chemical_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.WasteRecord)
    if status:
        query = query.filter(models.WasteRecord.status == status)
    if lab_id:
        query = query.filter(models.WasteRecord.lab_id == lab_id)
    if chemical_id:
        query = query.filter(models.WasteRecord.chemical_id == chemical_id)
    if current_user.role == models.UserRole.RESEARCHER:
        query = query.filter(models.WasteRecord.submitter_id == current_user.id)

    records = query.order_by(models.WasteRecord.created_at.desc()).offset(skip).limit(limit).all()
    return [
        schemas.WasteRecordResponse(
            id=w.id,
            waste_no=w.waste_no,
            chemical_id=w.chemical_id,
            chemical_name=w.chemical.name if w.chemical else None,
            lab_id=w.lab_id,
            waste_type=w.waste_type,
            quantity=w.quantity,
            unit=w.unit,
            container_no=w.container_no,
            container_type=w.container_type,
            seal_inspection_passed=w.seal_inspection_passed,
            seal_inspection_notes=w.seal_inspection_notes,
            label_inspection_passed=w.label_inspection_passed,
            label_inspection_notes=w.label_inspection_notes,
            violation_recorded=w.violation_recorded,
            violation_type=w.violation_type,
            violation_notes=w.violation_notes,
            status=w.status,
            batch_id=w.batch_id,
            disposal_center_id=w.disposal_center_id,
            created_at=w.created_at,
            inspected_at=w.inspected_at
        ) for w in records
    ]


@router_waste.get("/batches", response_model=List[schemas.WasteBatchResponse])
def list_waste_batches(
    status: Optional[str] = None,
    disposal_center_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.WasteBatch)
    if status:
        query = query.filter(models.WasteBatch.status == status)
    if disposal_center_id:
        query = query.filter(models.WasteBatch.disposal_center_id == disposal_center_id)
    batches = query.order_by(models.WasteBatch.created_at.desc()).offset(skip).limit(limit).all()

    return [
        schemas.WasteBatchResponse(
            id=b.id,
            batch_no=b.batch_no,
            disposal_center_id=b.disposal_center_id,
            transport_company=b.transport_company,
            driver_name=b.driver_name,
            vehicle_plate=b.vehicle_plate,
            manifest_no=b.manifest_no,
            total_quantity=b.total_quantity,
            status=b.status,
            created_at=b.created_at,
            shipped_at=b.shipped_at,
            received_at=b.received_at
        ) for b in batches
    ]


router_disposal = APIRouter(prefix="/api/disposal-centers", tags=["处理中心"])


@router_disposal.post("", response_model=schemas.DisposalCenterResponse, dependencies=[Depends(require_roles(models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER))])
def create_disposal_center(center_in: schemas.DisposalCenterBase, db: Session = Depends(get_db)):
    if db.query(models.DisposalCenter).filter(models.DisposalCenter.code == center_in.code).first():
        raise HTTPException(status_code=400, detail="处理中心编码已存在")
    center = models.DisposalCenter(**center_in.model_dump())
    db.add(center)
    db.commit()
    db.refresh(center)
    return center


@router_disposal.get("", response_model=List[schemas.DisposalCenterResponse])
def list_disposal_centers(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    return db.query(models.DisposalCenter).filter(models.DisposalCenter.is_active == True).offset(skip).limit(limit).all()


def auto_generate_single_replenishment(db: Session, chemical_id: int, created_by_id: Optional[int] = None) -> Optional[models.ReplenishmentRequest]:
    chemical = db.query(models.Chemical).filter(models.Chemical.id == chemical_id).first()
    if not chemical:
        return None

    existing = db.query(models.ReplenishmentRequest).filter(
        models.ReplenishmentRequest.chemical_id == chemical_id,
        models.ReplenishmentRequest.status.in_([
            models.ReplenishmentStatus.PENDING_LAB_MANAGER,
            models.ReplenishmentStatus.LAB_MANAGER_APPROVED,
            models.ReplenishmentStatus.PENDING_SAFETY,
            models.ReplenishmentStatus.SYNCED_TO_PURCHASE
        ])
    ).first()
    if existing:
        return None

    inventories = db.query(models.Inventory).filter(models.Inventory.chemical_id == chemical_id).all()
    if not inventories:
        return None

    current_total = sum(inv.current_quantity for inv in inventories)
    safety_total = sum(inv.safety_level for inv in inventories)

    if current_total > safety_total:
        return None

    suggested_qty = max(safety_total * 2, safety_total * 1.5)
    request_no = generate_request_no("RP")
    unit = inventories[0].unit

    request = models.ReplenishmentRequest(
        request_no=request_no,
        chemical_id=chemical_id,
        current_quantity=round(current_total, 4),
        safety_level=round(safety_total, 4),
        requested_quantity=round(suggested_qty, 2),
        unit=unit,
        reason=f"系统自动生成：领用扣减后库存低于安全水位 (当前: {round(current_total,4)}{unit}, 安全: {round(safety_total,4)}{unit})",
        status=models.ReplenishmentStatus.PENDING_LAB_MANAGER,
        created_by_id=created_by_id,
        created_at=datetime.utcnow()
    )
    db.add(request)
    db.flush()

    notification_service.create_notification(
        db=db,
        notification_type=models.NotificationType.REPLENISHMENT,
        title=f"系统自动生成补货申请: {chemical.name}",
        content=f"申请单号: {request_no}, 当前库存: {round(current_total,4)}{unit}, 建议补货: {round(suggested_qty,2)}{unit}",
        roles=[models.UserRole.LAB_MANAGER],
        lab_id=chemical.lab_id,
        related_id=request.id,
        related_type="replenishment"
    )
    return request


@router_replenishment.post("", response_model=schemas.ReplenishmentResponse)
def create_replenishment(
    chemical_id: int,
    requested_quantity: float,
    unit: str,
    reason: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(models.UserRole.LAB_MANAGER, models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER))
):
    chemical = db.query(models.Chemical).filter(models.Chemical.id == chemical_id).first()
    if not chemical:
        raise HTTPException(status_code=404, detail="化学品不存在")

    inventories = db.query(models.Inventory).filter(models.Inventory.chemical_id == chemical_id).all()
    current_total = sum(inv.current_quantity for inv in inventories)
    safety_total = sum(inv.safety_level for inv in inventories)

    request_no = generate_request_no("RP")

    request = models.ReplenishmentRequest(
        request_no=request_no,
        chemical_id=chemical_id,
        current_quantity=current_total,
        safety_level=safety_total,
        requested_quantity=requested_quantity,
        unit=unit,
        reason=reason or f"当前库存 {current_total}{unit} 低于安全水位 {safety_total}{unit}",
        status=models.ReplenishmentStatus.PENDING_LAB_MANAGER,
        created_by_id=current_user.id,
        created_at=datetime.utcnow()
    )
    db.add(request)
    db.commit()
    db.refresh(request)

    notification_service.create_notification(
        db=db,
        notification_type=models.NotificationType.REPLENISHMENT,
        title=f"补货申请待审批: {chemical.name}",
        content=f"申请单号: {request_no}, 当前库存: {current_total}{unit}, 安全水位: {safety_total}{unit}, 申请数量: {requested_quantity}{unit}",
        roles=[models.UserRole.LAB_MANAGER],
        lab_id=chemical.lab_id,
        related_id=request.id,
        related_type="replenishment"
    )

    return schemas.ReplenishmentResponse(
        id=request.id,
        request_no=request.request_no,
        chemical_id=request.chemical_id,
        chemical_name=chemical.name,
        current_quantity=request.current_quantity,
        safety_level=request.safety_level,
        requested_quantity=request.requested_quantity,
        unit=request.unit,
        reason=request.reason,
        status=request.status,
        created_by_id=request.created_by_id,
        lab_manager_id=request.lab_manager_id,
        safety_officer_id=request.safety_officer_id,
        lab_manager_comment=request.lab_manager_comment,
        safety_officer_comment=request.safety_officer_comment,
        reminder_sent_count=request.reminder_sent_count,
        purchase_order_no=request.purchase_order_no,
        created_at=request.created_at,
        lab_manager_approved_at=request.lab_manager_approved_at,
        safety_officer_approved_at=request.safety_officer_approved_at
    )


@router_replenishment.post("/auto-generate", response_model=List[schemas.ReplenishmentResponse])
def auto_generate_low_stock_replenishment(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(models.UserRole.LAB_MANAGER, models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER))
):
    low_stock_items = db.query(models.Inventory).filter(
        models.Inventory.current_quantity <= models.Inventory.safety_level
    ).all()

    grouped = {}
    for inv in low_stock_items:
        if inv.chemical_id not in grouped:
            grouped[inv.chemical_id] = {
                "current": 0,
                "safety": 0,
                "unit": inv.unit,
                "name": inv.chemical.name if inv.chemical else f"Chemical_{inv.chemical_id}",
                "chemical": inv.chemical
            }
        grouped[inv.chemical_id]["current"] += inv.current_quantity
        grouped[inv.chemical_id]["safety"] += inv.safety_level

    generated = []
    for chemical_id, data in grouped.items():
        suggested_qty = max(data["safety"] * 2, data["safety"] * 1.5)
        existing = db.query(models.ReplenishmentRequest).filter(
            models.ReplenishmentRequest.chemical_id == chemical_id,
            models.ReplenishmentRequest.status.in_([
                models.ReplenishmentStatus.PENDING_LAB_MANAGER,
                models.ReplenishmentStatus.LAB_MANAGER_APPROVED,
                models.ReplenishmentStatus.PENDING_SAFETY
            ])
        ).first()
        if existing:
            continue

        request_no = generate_request_no("RP")
        request = models.ReplenishmentRequest(
            request_no=request_no,
            chemical_id=chemical_id,
            current_quantity=data["current"],
            safety_level=data["safety"],
            requested_quantity=round(suggested_qty, 2),
            unit=data["unit"],
            reason=f"系统自动生成：库存低于安全水位 (当前: {data['current']}, 安全: {data['safety']})",
            status=models.ReplenishmentStatus.PENDING_LAB_MANAGER,
            created_by_id=current_user.id,
            created_at=datetime.utcnow()
        )
        db.add(request)
        db.flush()
        generated.append(request)

        chemical = data["chemical"]
        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.REPLENISHMENT,
            title=f"系统自动生成补货申请: {data['name']}",
            content=f"申请单号: {request_no}, 当前库存: {data['current']}{data['unit']}, 建议补货: {round(suggested_qty, 2)}{data['unit']}",
            roles=[models.UserRole.LAB_MANAGER],
            lab_id=chemical.lab_id if chemical else None,
            related_id=request.id,
            related_type="replenishment"
        )

    db.commit()

    responses = []
    for req in generated:
        responses.append(schemas.ReplenishmentResponse(
            id=req.id,
            request_no=req.request_no,
            chemical_id=req.chemical_id,
            chemical_name=req.chemical.name if req.chemical else None,
            current_quantity=req.current_quantity,
            safety_level=req.safety_level,
            requested_quantity=req.requested_quantity,
            unit=req.unit,
            reason=req.reason,
            status=req.status,
            created_by_id=req.created_by_id,
            lab_manager_id=req.lab_manager_id,
            safety_officer_id=req.safety_officer_id,
            lab_manager_comment=req.lab_manager_comment,
            safety_officer_comment=req.safety_officer_comment,
            reminder_sent_count=req.reminder_sent_count,
            purchase_order_no=req.purchase_order_no,
            created_at=req.created_at,
            lab_manager_approved_at=req.lab_manager_approved_at,
            safety_officer_approved_at=req.safety_officer_approved_at
        ))
    return responses


@router_replenishment.post("/{request_id}/lab-manager-review", response_model=schemas.ReplenishmentResponse)
def lab_manager_review(
    request_id: int,
    review_in: schemas.ReplenishmentReview,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(models.UserRole.LAB_MANAGER, models.UserRole.ADMIN))
):
    request = db.query(models.ReplenishmentRequest).filter(models.ReplenishmentRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="补货申请不存在")
    if request.status != models.ReplenishmentStatus.PENDING_LAB_MANAGER:
        raise HTTPException(status_code=400, detail="当前状态不需要实验室主任审批")

    request.lab_manager_id = current_user.id
    request.lab_manager_comment = review_in.comment
    request.lab_manager_approved_at = datetime.utcnow()

    if review_in.approved:
        request.status = models.ReplenishmentStatus.PENDING_SAFETY
        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.REPLENISHMENT,
            title=f"补货申请待安环审批: {request.chemical.name if request.chemical else ''}",
            content=f"申请单号: {request.request_no}, 申请数量: {request.requested_quantity}{request.unit}",
            roles=[models.UserRole.SAFETY_OFFICER],
            related_id=request.id,
            related_type="replenishment"
        )
        dispatch_ws_event(
            notification_type="replenishment",
            event="lab_manager_approved",
            data={
                "id": request.id,
                "request_no": request.request_no,
                "chemical_id": request.chemical_id,
                "chemical_name": request.chemical.name if request.chemical else None,
                "current_quantity": request.current_quantity,
                "safety_level": request.safety_level,
                "requested_quantity": request.requested_quantity,
                "unit": request.unit,
                "reviewer_id": current_user.id,
                "reviewer_name": current_user.real_name,
                "review_comment": review_in.comment,
                "status": "pending_safety"
            },
            user_ids=[request.created_by_id, current_user.id],
            roles=[models.UserRole.SAFETY_OFFICER, models.UserRole.LAB_MANAGER, models.UserRole.ADMIN]
        )
    else:
        request.status = models.ReplenishmentStatus.LAB_MANAGER_REJECTED
        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.REPLENISHMENT,
            title=f"补货申请被主任驳回",
            content=f"申请单号: {request.request_no}, 原因: {review_in.comment or '未说明'}",
            user_ids=[request.created_by_id],
            related_id=request.id,
            related_type="replenishment"
        )
        dispatch_ws_event(
            notification_type="replenishment",
            event="lab_manager_rejected",
            data={
                "id": request.id,
                "request_no": request.request_no,
                "chemical_id": request.chemical_id,
                "chemical_name": request.chemical.name if request.chemical else None,
                "current_quantity": request.current_quantity,
                "safety_level": request.safety_level,
                "requested_quantity": request.requested_quantity,
                "unit": request.unit,
                "reviewer_id": current_user.id,
                "reviewer_name": current_user.real_name,
                "reject_reason": review_in.comment or "未说明",
                "status": "lab_manager_rejected"
            },
            user_ids=[request.created_by_id, current_user.id],
            roles=[models.UserRole.LAB_MANAGER, models.UserRole.ADMIN]
        )

    db.commit()
    db.refresh(request)

    return schemas.ReplenishmentResponse(
        id=request.id,
        request_no=request.request_no,
        chemical_id=request.chemical_id,
        chemical_name=request.chemical.name if request.chemical else None,
        current_quantity=request.current_quantity,
        safety_level=request.safety_level,
        requested_quantity=request.requested_quantity,
        unit=request.unit,
        reason=request.reason,
        status=request.status,
        created_by_id=request.created_by_id,
        lab_manager_id=request.lab_manager_id,
        safety_officer_id=request.safety_officer_id,
        lab_manager_comment=request.lab_manager_comment,
        safety_officer_comment=request.safety_officer_comment,
        reminder_sent_count=request.reminder_sent_count,
        purchase_order_no=request.purchase_order_no,
        created_at=request.created_at,
        lab_manager_approved_at=request.lab_manager_approved_at,
        safety_officer_approved_at=request.safety_officer_approved_at
    )


@router_replenishment.post("/{request_id}/safety-review", response_model=schemas.ReplenishmentResponse)
def safety_officer_review(
    request_id: int,
    review_in: schemas.ReplenishmentReview,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(models.UserRole.SAFETY_OFFICER, models.UserRole.ADMIN))
):
    request = db.query(models.ReplenishmentRequest).filter(models.ReplenishmentRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="补货申请不存在")
    if request.status != models.ReplenishmentStatus.PENDING_SAFETY:
        raise HTTPException(status_code=400, detail="当前状态不需要安环部门审批")

    request.safety_officer_id = current_user.id
    request.safety_officer_comment = review_in.comment
    request.safety_officer_approved_at = datetime.utcnow()

    if review_in.approved:
        request.status = models.ReplenishmentStatus.SYNCED_TO_PURCHASE
        po_no = f"PO-{datetime.utcnow().strftime('%Y%m%d')}-{request.id}"
        request.purchase_order_no = po_no
        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.REPLENISHMENT,
            title=f"补货申请已通过，同步采购",
            content=f"申请单号: {request.request_no}, 采购单号: {po_no}, 化学品: {request.chemical.name if request.chemical else ''}",
            roles=[models.UserRole.LAB_MANAGER, models.UserRole.ADMIN],
            user_ids=[request.created_by_id],
            related_id=request.id,
            related_type="replenishment"
        )
        dispatch_ws_event(
            notification_type="replenishment",
            event="safety_approved",
            data={
                "id": request.id,
                "request_no": request.request_no,
                "chemical_id": request.chemical_id,
                "chemical_name": request.chemical.name if request.chemical else None,
                "current_quantity": request.current_quantity,
                "safety_level": request.safety_level,
                "requested_quantity": request.requested_quantity,
                "unit": request.unit,
                "reviewer_id": current_user.id,
                "reviewer_name": current_user.real_name,
                "review_comment": review_in.comment,
                "purchase_order_no": po_no,
                "status": "synced_to_purchase"
            },
            user_ids=[request.created_by_id, current_user.id],
            roles=[models.UserRole.SAFETY_OFFICER, models.UserRole.LAB_MANAGER, models.UserRole.ADMIN]
        )
    else:
        request.status = models.ReplenishmentStatus.SAFETY_REJECTED
        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.REPLENISHMENT,
            title=f"补货申请被安环驳回",
            content=f"申请单号: {request.request_no}, 原因: {review_in.comment or '未说明'}",
            user_ids=[request.created_by_id],
            related_id=request.id,
            related_type="replenishment"
        )
        dispatch_ws_event(
            notification_type="replenishment",
            event="safety_rejected",
            data={
                "id": request.id,
                "request_no": request.request_no,
                "chemical_id": request.chemical_id,
                "chemical_name": request.chemical.name if request.chemical else None,
                "current_quantity": request.current_quantity,
                "safety_level": request.safety_level,
                "requested_quantity": request.requested_quantity,
                "unit": request.unit,
                "reviewer_id": current_user.id,
                "reviewer_name": current_user.real_name,
                "reject_reason": review_in.comment or "未说明",
                "status": "safety_rejected"
            },
            user_ids=[request.created_by_id, current_user.id],
            roles=[models.UserRole.SAFETY_OFFICER, models.UserRole.LAB_MANAGER, models.UserRole.ADMIN]
        )

    db.commit()
    db.refresh(request)

    return schemas.ReplenishmentResponse(
        id=request.id,
        request_no=request.request_no,
        chemical_id=request.chemical_id,
        chemical_name=request.chemical.name if request.chemical else None,
        current_quantity=request.current_quantity,
        safety_level=request.safety_level,
        requested_quantity=request.requested_quantity,
        unit=request.unit,
        reason=request.reason,
        status=request.status,
        created_by_id=request.created_by_id,
        lab_manager_id=request.lab_manager_id,
        safety_officer_id=request.safety_officer_id,
        lab_manager_comment=request.lab_manager_comment,
        safety_officer_comment=request.safety_officer_comment,
        reminder_sent_count=request.reminder_sent_count,
        purchase_order_no=request.purchase_order_no,
        created_at=request.created_at,
        lab_manager_approved_at=request.lab_manager_approved_at,
        safety_officer_approved_at=request.safety_officer_approved_at
    )


@router_replenishment.post("/check-reminders")
def check_and_send_reminders(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER))
):
    pending_statuses = [
        models.ReplenishmentStatus.PENDING_LAB_MANAGER,
        models.ReplenishmentStatus.PENDING_SAFETY
    ]
    threshold_hours = 24
    since = datetime.utcnow() - timedelta(hours=threshold_hours)

    pending_requests = db.query(models.ReplenishmentRequest).filter(
        models.ReplenishmentRequest.status.in_(pending_statuses),
        models.ReplenishmentRequest.created_at <= since
    ).all()

    reminded_count = 0
    for req in pending_requests:
        last_sent = req.last_reminder_sent_at
        if last_sent and (datetime.utcnow() - last_sent).total_seconds() < threshold_hours * 3600:
            continue

        role_map = {
            models.ReplenishmentStatus.PENDING_LAB_MANAGER: [models.UserRole.LAB_MANAGER],
            models.ReplenishmentStatus.PENDING_SAFETY: [models.UserRole.SAFETY_OFFICER]
        }
        roles = role_map.get(req.status, [])
        stage = "实验室主任审批" if req.status == models.ReplenishmentStatus.PENDING_LAB_MANAGER else "安环部门审批"

        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.REPLENISHMENT,
            title=f"【催办】补货申请超时未处理",
            content=f"申请单号: {req.request_no}, 当前阶段: {stage}, 已等待超过{threshold_hours}小时，请及时处理",
            roles=roles,
            related_id=req.id,
            related_type="replenishment"
        )
        req.reminder_sent_count += 1
        req.last_reminder_sent_at = datetime.utcnow()
        reminded_count += 1

    db.commit()
    return {"reminded_count": reminded_count, "total_pending": len(pending_requests)}


@router_replenishment.get("", response_model=List[schemas.ReplenishmentResponse])
def list_replenishment_requests(
    status: Optional[str] = None,
    chemical_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.ReplenishmentRequest)
    if status:
        query = query.filter(models.ReplenishmentRequest.status == status)
    if chemical_id:
        query = query.filter(models.ReplenishmentRequest.chemical_id == chemical_id)
    if current_user.role == models.UserRole.LAB_MANAGER and status is None:
        query = query.filter(models.ReplenishmentRequest.status.in_([
            models.ReplenishmentStatus.PENDING_LAB_MANAGER,
            models.ReplenishmentStatus.LAB_MANAGER_APPROVED,
            models.ReplenishmentStatus.LAB_MANAGER_REJECTED
        ]))
    if current_user.role == models.UserRole.SAFETY_OFFICER and status is None:
        query = query.filter(models.ReplenishmentRequest.status.in_([
            models.ReplenishmentStatus.PENDING_SAFETY,
            models.ReplenishmentStatus.SAFETY_APPROVED,
            models.ReplenishmentStatus.SAFETY_REJECTED
        ]))

    requests = query.order_by(models.ReplenishmentRequest.created_at.desc()).offset(skip).limit(limit).all()
    return [
        schemas.ReplenishmentResponse(
            id=r.id,
            request_no=r.request_no,
            chemical_id=r.chemical_id,
            chemical_name=r.chemical.name if r.chemical else None,
            current_quantity=r.current_quantity,
            safety_level=r.safety_level,
            requested_quantity=r.requested_quantity,
            unit=r.unit,
            reason=r.reason,
            status=r.status,
            created_by_id=r.created_by_id,
            lab_manager_id=r.lab_manager_id,
            safety_officer_id=r.safety_officer_id,
            lab_manager_comment=r.lab_manager_comment,
            safety_officer_comment=r.safety_officer_comment,
            reminder_sent_count=r.reminder_sent_count,
            purchase_order_no=r.purchase_order_no,
            created_at=r.created_at,
            lab_manager_approved_at=r.lab_manager_approved_at,
            safety_officer_approved_at=r.safety_officer_approved_at
        ) for r in requests
    ]
