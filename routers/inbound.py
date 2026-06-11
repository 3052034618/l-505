from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, date
from database import get_db
from auth import get_current_user, require_roles, generate_request_no
from notification_service import notification_service
import models
import schemas

from routers.websocket import dispatch_ws_event
from event_service import event_service

router_inbound = APIRouter(prefix="/api/inbound", tags=["危化品入库"])


def verify_msds(chemical: models.Chemical, msds_data: Optional[dict]) -> schemas.MsdsVerificationResult:
    issues = []
    warnings = []

    if not msds_data and not chemical.msds_data:
        issues.append("缺少MSDS数据文件")
        return schemas.MsdsVerificationResult(verified=False, issues=issues, warnings=warnings)

    data = msds_data or chemical.msds_data or {}

    required_fields = ["hazard_statements", "signal_word", "emergency_measures"]
    for field in required_fields:
        if field not in data or not data[field]:
            issues.append(f"MSDS缺少必填字段: {field}")

    if "hazard_statements" in data and data["hazard_statements"]:
        for h in data["hazard_statements"]:
            if h.startswith("H3") or h.startswith("H2"):
                if chemical.hazard_level in [models.HazardLevel.LOW, models.HazardLevel.MEDIUM]:
                    warnings.append(f"危险声明 {h} 对应的危害等级可能偏低，建议确认")

    if "flash_point" in data and data["flash_point"] is not None:
        if data["flash_point"] < 23 and chemical.category != models.ChemicalCategory.FLAMMABLE:
            issues.append(f"闪点 {data['flash_point']}°C 低于23°C，应归类为易燃化学品")
        elif 23 <= data["flash_point"] < 60 and chemical.category != models.ChemicalCategory.FLAMMABLE:
            warnings.append(f"闪点 {data['flash_point']}°C 在23-60°C之间，建议确认是否为易燃类")

    if "toxicity_data" in data and data["toxicity_data"]:
        ld50 = data["toxicity_data"].get("oral_rat_ld50")
        if ld50 and ld50 < 50 and chemical.hazard_level != models.HazardLevel.EXTREME:
            issues.append(f"LD50={ld50}mg/kg 属于剧毒，危害等级应为EXTREME")
        elif ld50 and ld50 < 300 and chemical.hazard_level not in [models.HazardLevel.HIGH, models.HazardLevel.EXTREME]:
            warnings.append(f"LD50={ld50}mg/kg 毒性较高，建议提高危害等级")

    if "storage_conditions" in data and data["storage_conditions"]:
        storage = data["storage_conditions"]
        if storage.get("incompatible_with"):
            if not chemical.incompatible_chemicals:
                warnings.append("MSDS包含不相容化学品信息，建议补充到化学品档案中")

    verified = len(issues) == 0
    return schemas.MsdsVerificationResult(verified=verified, issues=issues, warnings=warnings)


def allocate_cabinet(chemical: models.Chemical, quantity: float, lab_id: Optional[int], db: Session) -> schemas.CabinetAllocationResult:
    query = db.query(models.StorageCabinet).filter(models.StorageCabinet.is_active == True)
    if lab_id:
        query = query.filter(models.StorageCabinet.lab_id == lab_id)
    cabinets = query.all()

    if not cabinets:
        return schemas.CabinetAllocationResult(allocated=False, reason="系统中没有可用的存储柜")

    category_str = chemical.category.value if hasattr(chemical.category, 'value') else str(chemical.category)
    hazard_str = chemical.hazard_level.value if hasattr(chemical.hazard_level, 'value') else str(chemical.hazard_level)

    import json as _json
    def _parse_json_list(val):
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

    scored_cabinets = []
    for cabinet in cabinets:
        score = 0

        allowed_cats = _parse_json_list(cabinet.allowed_categories)
        allowed_hazards = _parse_json_list(cabinet.allowed_hazard_levels)

        if allowed_cats:
            if category_str in allowed_cats:
                score += 50
            else:
                continue

        if allowed_hazards:
            if hazard_str in allowed_hazards:
                score += 30
            else:
                continue

        if chemical.storage_temp_min is not None and cabinet.temperature_min is not None:
            if cabinet.temperature_min <= chemical.storage_temp_min:
                score += 10
            else:
                continue

        if chemical.storage_temp_max is not None and cabinet.temperature_max is not None:
            if cabinet.temperature_max >= chemical.storage_temp_max:
                score += 10
            else:
                continue

        if chemical.storage_humidity_min is not None and cabinet.humidity_min is not None:
            if cabinet.humidity_min <= chemical.storage_humidity_min:
                score += 5

        if chemical.storage_humidity_max is not None and cabinet.humidity_max is not None:
            if cabinet.humidity_max >= chemical.storage_humidity_max:
                score += 5

        if chemical.hazard_level in [models.HazardLevel.HIGH, models.HazardLevel.EXTREME]:
            if cabinet.has_fire_extinguisher:
                score += 15
            if cabinet.has_ventilation:
                score += 10

        available_space = cabinet.capacity - cabinet.current_occupancy
        if available_space < quantity:
            continue
        if available_space / cabinet.capacity > 0.3:
            score += 10

        if score > 0:
            scored_cabinets.append((cabinet, score))

    if not scored_cabinets:
        return schemas.CabinetAllocationResult(allocated=False, reason="没有符合存储条件的可用存储柜，请检查类别/温湿度/容量限制")

    scored_cabinets.sort(key=lambda x: x[1], reverse=True)
    best_cabinet = scored_cabinets[0][0]

    temp_min = chemical.storage_temp_min if chemical.storage_temp_min is not None else best_cabinet.temperature_min
    temp_max = chemical.storage_temp_max if chemical.storage_temp_max is not None else best_cabinet.temperature_max
    hum_min = chemical.storage_humidity_min if chemical.storage_humidity_min is not None else best_cabinet.humidity_min
    hum_max = chemical.storage_humidity_max if chemical.storage_humidity_max is not None else best_cabinet.humidity_max

    return schemas.CabinetAllocationResult(
        cabinet_id=best_cabinet.id,
        cabinet_no=best_cabinet.cabinet_no,
        allocated=True,
        temp_threshold_min=temp_min,
        temp_threshold_max=temp_max,
        humidity_threshold_min=hum_min,
        humidity_threshold_max=hum_max
    )


@router_inbound.post("", response_model=schemas.InboundResponse)
def create_inbound(
    inbound_in: schemas.InboundRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER, models.UserRole.LAB_MANAGER))
):
    chemical = db.query(models.Chemical).filter(models.Chemical.id == inbound_in.chemical_id).first()
    if not chemical:
        raise HTTPException(status_code=404, detail="化学品不存在")

    msds_result = verify_msds(chemical, inbound_in.msds_data)

    cabinet_result = allocate_cabinet(chemical, inbound_in.quantity, chemical.lab_id, db)

    record = models.InboundRecord(
        chemical_id=inbound_in.chemical_id,
        batch_no=inbound_in.batch_no,
        quantity=inbound_in.quantity,
        unit=inbound_in.unit,
        manufacturer=inbound_in.manufacturer,
        production_date=inbound_in.production_date,
        expiry_date=inbound_in.expiry_date,
        msds_verified=msds_result.verified,
        msds_verify_result="问题: " + "; ".join(msds_result.issues) + ("; 警告: " + "; ".join(msds_result.warnings) if msds_result.warnings else "") if (msds_result.issues or msds_result.warnings) else "MSDS合规",
        cabinet_allocated=cabinet_result.allocated,
        allocated_cabinet_id=cabinet_result.cabinet_id,
        status="approved" if (msds_result.verified and cabinet_result.allocated) else "rejected",
        reject_reason=None if (msds_result.verified and cabinet_result.allocated) else f"MSDS校验: {'通过' if msds_result.verified else '未通过'} | 柜位分配: {cabinet_result.reason or '已分配'}",
        operator_id=current_user.id,
        admin_notified=False,
        created_at=datetime.utcnow()
    )
    db.add(record)
    db.flush()

    if msds_result.verified and cabinet_result.allocated:
        existing_inventory = db.query(models.Inventory).filter(
            models.Inventory.chemical_id == inbound_in.chemical_id,
            models.Inventory.batch_no == inbound_in.batch_no,
            models.Inventory.cabinet_id == cabinet_result.cabinet_id
        ).first()

        if existing_inventory:
            existing_inventory.quantity += inbound_in.quantity
            existing_inventory.current_quantity += inbound_in.quantity
            record.inventory_id = existing_inventory.id
        else:
            default_safety = inbound_in.quantity * 0.2
            inventory = models.Inventory(
                chemical_id=inbound_in.chemical_id,
                cabinet_id=cabinet_result.cabinet_id,
                batch_no=inbound_in.batch_no,
                quantity=inbound_in.quantity,
                unit=inbound_in.unit,
                current_quantity=inbound_in.quantity,
                safety_level=default_safety,
                manufacturer=inbound_in.manufacturer,
                production_date=inbound_in.production_date,
                expiry_date=inbound_in.expiry_date,
                temp_threshold_min=cabinet_result.temp_threshold_min,
                temp_threshold_max=cabinet_result.temp_threshold_max,
                humidity_threshold_min=cabinet_result.humidity_threshold_min,
                humidity_threshold_max=cabinet_result.humidity_threshold_max,
                status="normal",
                created_at=datetime.utcnow()
            )
            db.add(inventory)
            db.flush()
            record.inventory_id = inventory.id

        cabinet = db.query(models.StorageCabinet).filter(models.StorageCabinet.id == cabinet_result.cabinet_id).first()
        if cabinet:
            cabinet.current_occupancy = min(cabinet.capacity, cabinet.current_occupancy + inbound_in.quantity)

        record.approved_at = datetime.utcnow()
        record.admin_notified = True

        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.INBOUND,
            title=f"化学品入库成功: {chemical.name}",
            content=f"批次号: {inbound_in.batch_no}, 数量: {inbound_in.quantity}{inbound_in.unit}, 柜位: {cabinet_result.cabinet_no}",
            lab_id=chemical.lab_id,
            roles=[models.UserRole.SAFETY_OFFICER, models.UserRole.LAB_MANAGER],
            related_id=record.id,
            related_type="inbound"
        )
        dispatch_ws_event(
            notification_type="inbound",
            event="approved",
            data={
                "id": record.id,
                "business_id": record.id,
                "business_no": inbound_in.batch_no,
                "chemical_id": inbound_in.chemical_id,
                "chemical_name": chemical.name,
                "batch_no": inbound_in.batch_no,
                "quantity": inbound_in.quantity,
                "unit": inbound_in.unit,
                "cabinet_no": cabinet_result.cabinet_no,
                "status": "approved"
            },
            lab_id=chemical.lab_id,
            roles=[models.UserRole.SAFETY_OFFICER, models.UserRole.LAB_MANAGER, models.UserRole.RESEARCHER, models.UserRole.SUPERVISOR]
        )
        event_service.add_audit_trail(
            db=db,
            business_type=models.EventBusinessType.INBOUND,
            business_id=record.id,
            business_no=inbound_in.batch_no,
            action="入库审核通过并上架",
            stage_name="MSDS审核+柜位分配→入库成功",
            from_status="pending",
            to_status="approved",
            operator_id=current_user.id,
            operator_name=current_user.real_name,
            operator_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
            comment=f"柜位: {cabinet_result.cabinet_no}，MSDS验证通过，存储条件匹配",
        )
        event_service.log_event(
            db=db,
            business_type=models.EventBusinessType.INBOUND,
            event_type="approved",
            business_id=record.id,
            business_no=inbound_in.batch_no,
            title=f"化学品入库成功: {chemical.name} {inbound_in.quantity}{inbound_in.unit}",
            summary=f"柜位: {cabinet_result.cabinet_no} | 批次号: {inbound_in.batch_no}",
            lab_id=chemical.lab_id,
            operator_id=current_user.id,
            handle_status=models.EventHandleStatus.COMPLETED,
            detail_url=f"/inbound/{record.id}",
            extra_data={
                "chemical_name": chemical.name,
                "cabinet_no": cabinet_result.cabinet_no,
                "inventory_id": record.inventory_id,
            },
            emit_ws=False,
        )
    else:
        admin_ids = [u.id for u in db.query(models.User).filter(
            models.User.role.in_([models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER]),
            models.User.is_active == True
        ).all()]
        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.INBOUND,
            title=f"化学品入库被拒绝: {chemical.name}",
            content=f"批次号: {inbound_in.batch_no}, 原因: {record.reject_reason}",
            user_ids=admin_ids,
            related_id=record.id,
            related_type="inbound"
        )
        record.admin_notified = True
        dispatch_ws_event(
            notification_type="inbound",
            event="rejected",
            data={
                "id": record.id,
                "business_id": record.id,
                "business_no": inbound_in.batch_no,
                "chemical_id": inbound_in.chemical_id,
                "chemical_name": chemical.name,
                "batch_no": inbound_in.batch_no,
                "reject_reason": record.reject_reason,
                "status": "rejected"
            },
            lab_id=chemical.lab_id,
            roles=[models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER, models.UserRole.LAB_MANAGER]
        )
        event_service.add_audit_trail(
            db=db,
            business_type=models.EventBusinessType.INBOUND,
            business_id=record.id,
            business_no=inbound_in.batch_no,
            action="入库审核拒绝",
            stage_name="MSDS审核+柜位分配→拒绝",
            from_status="pending",
            to_status="rejected",
            operator_id=current_user.id,
            operator_name=current_user.real_name,
            operator_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
            comment=record.reject_reason,
        )
        event_service.log_event(
            db=db,
            business_type=models.EventBusinessType.INBOUND,
            event_type="rejected",
            business_id=record.id,
            business_no=inbound_in.batch_no,
            title=f"化学品入库被拒绝: {chemical.name}",
            summary=f"原因: {record.reject_reason}",
            lab_id=chemical.lab_id,
            operator_id=current_user.id,
            handle_status=models.EventHandleStatus.FAILED,
            detail_url=f"/inbound/{record.id}",
            extra_data={"reject_reason": record.reject_reason, "msds_verified": record.msds_verified},
            emit_ws=False,
        )

    db.commit()
    db.refresh(record)

    response = schemas.InboundResponse(
        id=record.id,
        chemical_id=record.chemical_id,
        batch_no=record.batch_no,
        quantity=record.quantity,
        unit=record.unit,
        msds_verified=record.msds_verified,
        msds_verify_result=record.msds_verify_result,
        cabinet_allocated=record.cabinet_allocated,
        allocated_cabinet_id=record.allocated_cabinet_id,
        status=record.status,
        reject_reason=record.reject_reason,
        admin_notified=record.admin_notified,
        created_at=record.created_at,
        msds_verification=msds_result,
        cabinet_allocation=cabinet_result
    )
    return response


@router_inbound.get("", response_model=List[schemas.InboundResponse])
def list_inbound(
    status: Optional[str] = None,
    chemical_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.InboundRecord)
    if status:
        query = query.filter(models.InboundRecord.status == status)
    if chemical_id:
        query = query.filter(models.InboundRecord.chemical_id == chemical_id)
    records = query.order_by(models.InboundRecord.created_at.desc()).offset(skip).limit(limit).all()

    responses = []
    for record in records:
        responses.append(schemas.InboundResponse(
            id=record.id,
            chemical_id=record.chemical_id,
            batch_no=record.batch_no,
            quantity=record.quantity,
            unit=record.unit,
            msds_verified=record.msds_verified,
            msds_verify_result=record.msds_verify_result,
            cabinet_allocated=record.cabinet_allocated,
            allocated_cabinet_id=record.allocated_cabinet_id,
            status=record.status,
            reject_reason=record.reject_reason,
            admin_notified=record.admin_notified,
            created_at=record.created_at
        ))
    return responses
