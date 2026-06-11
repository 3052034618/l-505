from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta, date
from database import get_db
from auth import get_current_user, require_roles, generate_request_no
from notification_service import notification_service
import models
import schemas

from routers.waste import auto_generate_single_replenishment
from routers.websocket import dispatch_ws_event
from event_service import event_service

router_usage = APIRouter(prefix="/api/usage", tags=["领用申请"])


def check_qualification(user: models.User, chemical: models.Chemical) -> schemas.QualificationCheckResult:
    issues = []

    if not user.qualification_cert_no:
        issues.append("申请人未上传危险化学品操作资质证书")
        return schemas.QualificationCheckResult(passed=False, message="缺少资质证书", issues=issues)

    if not user.qualification_expire_date:
        issues.append("资质证书缺少有效期信息")
        return schemas.QualificationCheckResult(passed=False, message="资质信息不完整", issues=issues)

    today = date.today()
    if user.qualification_expire_date < today:
        issues.append(f"资质证书已于 {user.qualification_expire_date} 过期")
        return schemas.QualificationCheckResult(passed=False, message="资质证书已过期", issues=issues)

    days_to_expire = (user.qualification_expire_date - today).days
    if days_to_expire < 30:
        issues.append(f"资质证书将于 {days_to_expire} 天后过期，请及时续期")

    if chemical.hazard_level in [models.HazardLevel.HIGH, models.HazardLevel.EXTREME]:
        if chemical.category in [models.ChemicalCategory.EXPLOSIVE, models.ChemicalCategory.CARCINOGENIC]:
            issues.append("该化学品为极高危类别，建议由资深人员操作")

    passed = not any("过期" in i or "缺少" in i or "未上传" in i for i in issues)
    message = "资质验证通过" if passed else "资质验证未通过"
    return schemas.QualificationCheckResult(passed=passed, message=message, issues=issues)


def check_usage_deviation(
    db: Session,
    user_id: int,
    chemical_id: int,
    project_type: models.ProjectType,
    requested_quantity: float
) -> schemas.UsageDeviationCheckResult:
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_requests = db.query(models.UsageRequest).filter(
        models.UsageRequest.requester_id == user_id,
        models.UsageRequest.chemical_id == chemical_id,
        models.UsageRequest.project_type == project_type,
        models.UsageRequest.status.in_([
            models.RequestStatus.AUTO_APPROVED,
            models.RequestStatus.SUPERVISOR_APPROVED,
            models.RequestStatus.COMPLETED
        ]),
        models.UsageRequest.created_at >= thirty_days_ago
    ).all()

    if not recent_requests:
        return schemas.UsageDeviationCheckResult(
            passed=True,
            message="无历史用量记录，首次申请按默认规则处理",
            deviation_ratio=None,
            historical_average=None
        )

    avg_quantity = sum(r.requested_quantity for r in recent_requests) / len(recent_requests)

    if avg_quantity <= 0:
        return schemas.UsageDeviationCheckResult(
            passed=True,
            message="历史数据异常，按默认规则处理",
            deviation_ratio=None,
            historical_average=None
        )

    deviation_ratio = requested_quantity / avg_quantity
    passed = deviation_ratio <= 2.0

    if deviation_ratio > 3.0:
        message = f"申请用量严重超出历史均值（偏差{round(deviation_ratio*100-100)}%），需导师审批"
    elif deviation_ratio > 2.0:
        message = f"申请用量明显超出历史均值（偏差{round(deviation_ratio*100-100)}%），需导师审批"
    elif deviation_ratio > 1.5:
        message = f"申请用量略高于历史均值（偏差{round(deviation_ratio*100-100)}%），系统已自动通过"
    else:
        message = "申请用量在历史合理范围内"

    return schemas.UsageDeviationCheckResult(
        passed=passed,
        message=message,
        deviation_ratio=round(deviation_ratio, 2),
        historical_average=round(avg_quantity, 4)
    )


def suggest_alternatives(db: Session, chemical: models.Chemical, project_type: models.ProjectType) -> List[schemas.AlternativeSuggestion]:
    suggestions = []

    if chemical.hazard_level in [models.HazardLevel.HIGH, models.HazardLevel.EXTREME]:
        alternatives = db.query(models.Chemical).filter(
            models.Chemical.category == chemical.category,
            models.Chemical.hazard_level.in_([models.HazardLevel.LOW, models.HazardLevel.MEDIUM]),
            models.Chemical.id != chemical.id,
            models.Chemical.is_active == True
        ).limit(5).all()

        for alt in alternatives:
            suggestion = schemas.AlternativeSuggestion(
                chemical_name=alt.name,
                reason=f"{alt.name}为同类低危替代品，危害等级为{alt.hazard_level.value}",
                estimated_safety_level=alt.hazard_level.value
            )
            suggestions.append(suggestion)

    if chemical.category == models.ChemicalCategory.CARCINOGENIC and not suggestions:
        suggestions.append(schemas.AlternativeSuggestion(
            chemical_name="考虑使用非致癌替代路线",
            reason="该化学品为致癌物，建议重新设计合成路线或使用物理方法",
            estimated_safety_level="safer"
        ))

    return suggestions


def check_safety_permission(user: models.User, chemical: models.Chemical, requested_quantity: float) -> tuple[bool, Optional[str]]:
    role_limits = {
        models.UserRole.RESEARCHER: {
            models.HazardLevel.EXTREME: 0.01,
            models.HazardLevel.HIGH: 0.5,
            models.HazardLevel.MEDIUM: 5.0,
            models.HazardLevel.LOW: 50.0
        },
        models.UserRole.SUPERVISOR: {
            models.HazardLevel.EXTREME: 0.1,
            models.HazardLevel.HIGH: 5.0,
            models.HazardLevel.MEDIUM: 50.0,
            models.HazardLevel.LOW: 500.0
        },
    }

    default_role = models.UserRole.RESEARCHER
    limits = role_limits.get(user.role, role_limits.get(default_role, {}))
    limit = limits.get(chemical.hazard_level)

    if limit is not None and requested_quantity > limit:
        return False, f"申请人角色[{user.role.value}]对{chemical.hazard_level.value}级化学品的单次最大允许量为{limit}，申请量{requested_quantity}超出权限"

    return True, None


@router_usage.post("", response_model=schemas.UsageRequestResponse)
def create_usage_request(
    request_in: schemas.UsageRequestCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    chemical = db.query(models.Chemical).filter(models.Chemical.id == request_in.chemical_id).first()
    if not chemical:
        raise HTTPException(status_code=404, detail="化学品不存在")

    lab = db.query(models.Laboratory).filter(models.Laboratory.id == request_in.lab_id).first()
    if not lab:
        raise HTTPException(status_code=404, detail="实验室不存在")

    total_available = db.query(models.Inventory).filter(
        models.Inventory.chemical_id == request_in.chemical_id
    ).all()
    available_qty = sum(inv.current_quantity for inv in total_available)
    if available_qty < request_in.requested_quantity:
        raise HTTPException(status_code=400, detail=f"库存不足。当前可用: {available_qty}{request_in.unit}，申请: {request_in.requested_quantity}{request_in.unit}")

    qualification_result = check_qualification(current_user, chemical)

    deviation_result = check_usage_deviation(
        db, current_user.id, request_in.chemical_id,
        request_in.project_type, request_in.requested_quantity
    )

    permission_ok, permission_msg = check_safety_permission(current_user, chemical, request_in.requested_quantity)

    alternatives = suggest_alternatives(db, chemical, request_in.project_type)

    auto_passed = True
    needs_supervisor = False
    block_reason = None
    alt_suggestion_text = None
    hard_rejected = False

    if not qualification_result.passed:
        auto_passed = False
        hard_rejected = True
        block_reason = " | ".join(qualification_result.issues)

    if not permission_ok:
        auto_passed = False
        needs_supervisor = True
        block_reason = (block_reason + " | " if block_reason else "") + permission_msg
        if alternatives:
            alt_suggestion_text = "; ".join([f"{s.chemical_name}: {s.reason}" for s in alternatives])

    if not deviation_result.passed or (deviation_result.deviation_ratio and deviation_result.deviation_ratio > 2.0):
        needs_supervisor = True
        if not block_reason:
            block_reason = deviation_result.message
        elif deviation_result.message and deviation_result.message not in block_reason:
            block_reason = block_reason + " | " + deviation_result.message

    if alternatives and (chemical.hazard_level in [models.HazardLevel.HIGH, models.HazardLevel.EXTREME]):
        if not alt_suggestion_text:
            alt_suggestion_text = "; ".join([f"{s.chemical_name}: {s.reason}" for s in alternatives])

    if hard_rejected:
        status_val = models.RequestStatus.AUTO_REJECTED
    elif needs_supervisor:
        status_val = models.RequestStatus.SUPERVISOR_PENDING
    else:
        status_val = models.RequestStatus.AUTO_APPROVED

    auto_review_details = schemas.AutoReviewResult(
        passed=auto_passed,
        needs_supervisor_approval=needs_supervisor,
        block_reason=block_reason,
        alternative_suggestions=alternatives,
        qualification_check=qualification_result,
        deviation_check=deviation_result
    )

    auto_review_text_parts = []
    auto_review_text_parts.append(f"资质验证: {'通过' if qualification_result.passed else '未通过'}")
    auto_review_text_parts.append(f"用量偏差: {deviation_result.message}")
    if permission_msg:
        auto_review_text_parts.append(f"权限检查: {permission_msg}")
    auto_review_result_text = " | ".join(auto_review_text_parts)

    request_no = generate_request_no("UR")

    request = models.UsageRequest(
        request_no=request_no,
        requester_id=current_user.id,
        lab_id=request_in.lab_id,
        chemical_id=request_in.chemical_id,
        project_type=request_in.project_type,
        project_name=request_in.project_name,
        requested_quantity=request_in.requested_quantity,
        unit=request_in.unit,
        purpose=request_in.purpose,
        qualification_verified=qualification_result.passed,
        qualification_verify_result=qualification_result.message + (": " + "; ".join(qualification_result.issues) if qualification_result.issues else ""),
        usage_deviation_checked=True,
        usage_deviation_ratio=deviation_result.deviation_ratio,
        auto_review_passed=auto_passed,
        block_reason=block_reason,
        alternative_suggestion=alt_suggestion_text,
        status=status_val,
        auto_review_result=auto_review_result_text,
        created_at=datetime.utcnow()
    )

    db.add(request)
    db.flush()

    if status_val == models.RequestStatus.AUTO_APPROVED:
        remaining = request_in.requested_quantity
        inventories = db.query(models.Inventory).filter(
            models.Inventory.chemical_id == request_in.chemical_id,
            models.Inventory.current_quantity > 0
        ).order_by(models.Inventory.expiry_date.asc()).all()
        for inv in inventories:
            if remaining <= 0:
                break
            deduct = min(inv.current_quantity, remaining)
            inv.current_quantity -= deduct
            remaining -= deduct
        request.status = models.RequestStatus.COMPLETED
        request.completed_at = datetime.utcnow()
        request.actual_quantity = request_in.requested_quantity

        auto_generate_single_replenishment(db, request_in.chemical_id, current_user.id)

        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.USAGE_REQUEST,
            title=f"领用申请自动通过: {chemical.name}",
            content=f"申请单号: {request_no}, 数量: {request_in.requested_quantity}{request_in.unit}, 项目: {request_in.project_name or request_in.project_type.value}",
            user_ids=[current_user.id],
            related_id=request.id,
            related_type="usage_request"
        )
        dispatch_ws_event(
            notification_type="usage",
            event="completed",
            data={
                "id": request.id,
                "request_no": request_no,
                "requester_id": current_user.id,
                "requester_name": current_user.real_name,
                "chemical_id": request_in.chemical_id,
                "chemical_name": chemical.name,
                "requested_quantity": request_in.requested_quantity,
                "unit": request_in.unit,
                "status": "completed"
            },
            user_ids=[current_user.id],
            lab_id=request_in.lab_id,
            roles=[models.UserRole.SAFETY_OFFICER, models.UserRole.LAB_MANAGER, models.UserRole.SUPERVISOR]
        )
        event_service.add_audit_trail(
            db=db,
            business_type=models.EventBusinessType.USAGE,
            business_id=request.id,
            business_no=request_no,
            action="系统自动审核通过",
            stage_name="自动审核",
            from_status="pending",
            to_status="completed",
            operator_id=None,
            operator_name="系统",
            operator_role="system",
            comment=f"资质有效、权限充足、用量正常。扣库存{request_in.requested_quantity}{request_in.unit}",
            extra_data={"auto_passed": True, "deduct_qty": request_in.requested_quantity},
        )
        event_service.log_event(
            db=db,
            business_type=models.EventBusinessType.USAGE,
            event_type="completed",
            business_id=request.id,
            business_no=request_no,
            title=f"领用申请已完成: {chemical.name} {request_in.requested_quantity}{request_in.unit}",
            summary=f"申请人: {current_user.real_name} | 项目: {request_in.project_name or request_in.project_type.value}",
            lab_id=request_in.lab_id,
            operator_id=current_user.id,
            target_user_id=current_user.id,
            handle_status=models.EventHandleStatus.COMPLETED,
            detail_url=f"/usage/{request.id}",
            extra_data={"requested_quantity": request_in.requested_quantity, "chemical_name": chemical.name},
            emit_ws=False,
        )

    elif status_val == models.RequestStatus.SUPERVISOR_PENDING:
        supervisors = db.query(models.User).filter(
            models.User.role == models.UserRole.SUPERVISOR,
            models.User.lab_id == request_in.lab_id,
            models.User.is_active == True
        ).all()
        if supervisors:
            request.supervisor_id = supervisors[0].id

        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.USAGE_REQUEST,
            title=f"领用申请待审批: {chemical.name}",
            content=f"申请人: {current_user.real_name}, 数量: {request_in.requested_quantity}{request_in.unit}, 原因: {block_reason or deviation_result.message}",
            roles=[models.UserRole.SUPERVISOR],
            lab_id=request_in.lab_id,
            related_id=request.id,
            related_type="usage_request"
        )
        dispatch_ws_event(
            notification_type="usage",
            event="supervisor_pending",
            data={
                "id": request.id,
                "request_no": request_no,
                "requester_id": current_user.id,
                "requester_name": current_user.real_name,
                "chemical_id": request_in.chemical_id,
                "chemical_name": chemical.name,
                "requested_quantity": request_in.requested_quantity,
                "unit": request_in.unit,
                "block_reason": block_reason or deviation_result.message,
                "status": "supervisor_pending"
            },
            user_ids=[current_user.id],
            lab_id=request_in.lab_id,
            roles=[models.UserRole.SUPERVISOR, models.UserRole.LAB_MANAGER]
        )
        event_service.add_audit_trail(
            db=db,
            business_type=models.EventBusinessType.USAGE,
            business_id=request.id,
            business_no=request_no,
            action="提交导师审批",
            stage_name="自动审核->导师审批",
            from_status="pending",
            to_status="supervisor_pending",
            operator_id=None,
            operator_name="系统",
            operator_role="system",
            comment=block_reason or deviation_result.message,
            extra_data={"needs_supervisor": True},
        )
        event_service.log_event(
            db=db,
            business_type=models.EventBusinessType.USAGE,
            event_type="supervisor_pending",
            business_id=request.id,
            business_no=request_no,
            title=f"领用申请待导师审批: {chemical.name}",
            summary=f"申请人: {current_user.real_name} | 原因: {block_reason or deviation_result.message}",
            lab_id=request_in.lab_id,
            operator_id=current_user.id,
            target_role=models.UserRole.SUPERVISOR.value,
            handle_status=models.EventHandleStatus.PENDING,
            detail_url=f"/usage/{request.id}",
            extra_data={"chemical_name": chemical.name, "requester_name": current_user.real_name},
            emit_ws=False,
        )
    else:
        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.USAGE_REQUEST,
            title=f"领用申请被拦截: {chemical.name}",
            content=f"申请单号: {request_no}, 原因: {block_reason or '系统自动拦截'}. " + (f"替代方案: {alt_suggestion_text}" if alt_suggestion_text else ""),
            user_ids=[current_user.id],
            related_id=request.id,
            related_type="usage_request"
        )
        dispatch_ws_event(
            notification_type="usage",
            event="auto_rejected",
            data={
                "id": request.id,
                "request_no": request_no,
                "requester_id": current_user.id,
                "requester_name": current_user.real_name,
                "chemical_id": request_in.chemical_id,
                "chemical_name": chemical.name,
                "requested_quantity": request_in.requested_quantity,
                "unit": request_in.unit,
                "block_reason": block_reason or "系统自动拦截",
                "alternative_suggestion": alt_suggestion_text,
                "status": "auto_rejected"
            },
            user_ids=[current_user.id],
            lab_id=request_in.lab_id,
            roles=[models.UserRole.SAFETY_OFFICER, models.UserRole.LAB_MANAGER]
        )
        event_service.add_audit_trail(
            db=db,
            business_type=models.EventBusinessType.USAGE,
            business_id=request.id,
            business_no=request_no,
            action="系统自动拦截拒绝",
            stage_name="自动审核",
            from_status="pending",
            to_status="auto_rejected",
            operator_id=None,
            operator_name="系统",
            operator_role="system",
            comment=block_reason or "系统自动拦截",
            extra_data={"hard_rejected": True},
        )
        event_service.log_event(
            db=db,
            business_type=models.EventBusinessType.USAGE,
            event_type="auto_rejected",
            business_id=request.id,
            business_no=request_no,
            title=f"领用申请被拦截: {chemical.name}",
            summary=f"申请人: {current_user.real_name} | 原因: {block_reason or '系统自动拦截'}",
            lab_id=request_in.lab_id,
            operator_id=current_user.id,
            target_user_id=current_user.id,
            handle_status=models.EventHandleStatus.FAILED,
            detail_url=f"/usage/{request.id}",
            extra_data={"chemical_name": chemical.name, "alternative_suggestion": alt_suggestion_text},
            emit_ws=False,
        )

    db.commit()
    db.refresh(request)

    response = schemas.UsageRequestResponse(
        id=request.id,
        request_no=request.request_no,
        requester_id=request.requester_id,
        requester_name=current_user.real_name,
        supervisor_id=request.supervisor_id,
        lab_id=request.lab_id,
        chemical_id=request.chemical_id,
        chemical_name=chemical.name,
        project_type=request.project_type,
        project_name=request.project_name,
        requested_quantity=request.requested_quantity,
        unit=request.unit,
        purpose=request.purpose,
        status=request.status,
        block_reason=request.block_reason,
        alternative_suggestion=request.alternative_suggestion,
        supervisor_review_comment=request.supervisor_review_comment,
        auto_review_result=request.auto_review_result,
        auto_review_details=auto_review_details,
        created_at=request.created_at,
        supervisor_reviewed_at=request.supervisor_reviewed_at,
        completed_at=request.completed_at
    )
    return response


@router_usage.get("", response_model=List[schemas.UsageRequestResponse])
def list_usage_requests(
    status: Optional[str] = None,
    requester_id: Optional[int] = None,
    lab_id: Optional[int] = None,
    chemical_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.UsageRequest)
    if current_user.role == models.UserRole.RESEARCHER:
        query = query.filter(models.UsageRequest.requester_id == current_user.id)
    if current_user.role == models.UserRole.SUPERVISOR:
        query = query.filter(
            (models.UsageRequest.requester_id == current_user.id) |
            (models.UsageRequest.supervisor_id == current_user.id)
        )
    if status:
        query = query.filter(models.UsageRequest.status == status)
    if requester_id:
        query = query.filter(models.UsageRequest.requester_id == requester_id)
    if lab_id:
        query = query.filter(models.UsageRequest.lab_id == lab_id)
    if chemical_id:
        query = query.filter(models.UsageRequest.chemical_id == chemical_id)

    requests = query.order_by(models.UsageRequest.created_at.desc()).offset(skip).limit(limit).all()

    responses = []
    for req in requests:
        responses.append(schemas.UsageRequestResponse(
            id=req.id,
            request_no=req.request_no,
            requester_id=req.requester_id,
            requester_name=req.requester.real_name if req.requester else None,
            supervisor_id=req.supervisor_id,
            lab_id=req.lab_id,
            chemical_id=req.chemical_id,
            chemical_name=req.chemical.name if req.chemical else None,
            project_type=req.project_type,
            project_name=req.project_name,
            requested_quantity=req.requested_quantity,
            unit=req.unit,
            purpose=req.purpose,
            status=req.status,
            block_reason=req.block_reason,
            alternative_suggestion=req.alternative_suggestion,
            supervisor_review_comment=req.supervisor_review_comment,
            auto_review_result=req.auto_review_result,
            created_at=req.created_at,
            supervisor_reviewed_at=req.supervisor_reviewed_at,
            completed_at=req.completed_at
        ))
    return responses


@router_usage.post("/{request_id}/review", response_model=schemas.UsageRequestResponse)
def review_usage_request(
    request_id: int,
    review_in: schemas.UsageReviewRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(models.UserRole.SUPERVISOR, models.UserRole.ADMIN, models.UserRole.LAB_MANAGER))
):
    request = db.query(models.UsageRequest).filter(models.UsageRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="申请记录不存在")
    if request.status != models.RequestStatus.SUPERVISOR_PENDING:
        raise HTTPException(status_code=400, detail="当前状态不需要审批")

    if current_user.role == models.UserRole.SUPERVISOR:
        if request.supervisor_id and request.supervisor_id != current_user.id:
            raise HTTPException(status_code=403, detail="您不是该申请的指定审批人")

    request.supervisor_review_comment = review_in.comment
    request.supervisor_reviewed_at = datetime.utcnow()

    if review_in.approved:
        remaining = request.requested_quantity
        inventories = db.query(models.Inventory).filter(
            models.Inventory.chemical_id == request.chemical_id,
            models.Inventory.current_quantity > 0
        ).order_by(models.Inventory.expiry_date.asc()).all()
        for inv in inventories:
            if remaining <= 0:
                break
            deduct = min(inv.current_quantity, remaining)
            inv.current_quantity -= deduct
            remaining -= deduct
        request.status = models.RequestStatus.SUPERVISOR_APPROVED
        request.completed_at = datetime.utcnow()
        request.actual_quantity = request.requested_quantity

        auto_generate_single_replenishment(db, request.chemical_id, current_user.id)

        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.USAGE_REQUEST,
            title=f"导师已批准您的领用申请",
            content=f"申请单号: {request.request_no}, 化学品: {request.chemical.name if request.chemical else ''}, 数量: {request.requested_quantity}{request.unit}",
            user_ids=[request.requester_id],
            related_id=request.id,
            related_type="usage_request"
        )
        dispatch_ws_event(
            notification_type="usage",
            event="supervisor_approved",
            data={
                "id": request.id,
                "request_no": request.request_no,
                "requester_id": request.requester_id,
                "requester_name": request.requester.real_name if request.requester else None,
                "chemical_id": request.chemical_id,
                "chemical_name": request.chemical.name if request.chemical else None,
                "requested_quantity": request.requested_quantity,
                "unit": request.unit,
                "actual_quantity": request.actual_quantity,
                "supervisor_id": current_user.id,
                "supervisor_name": current_user.real_name,
                "review_comment": review_in.comment,
                "status": "supervisor_approved"
            },
            user_ids=[request.requester_id, current_user.id],
            lab_id=request.lab_id,
            roles=[models.UserRole.SAFETY_OFFICER, models.UserRole.LAB_MANAGER, models.UserRole.SUPERVISOR]
        )
        wait_duration = None
        if request.created_at and request.supervisor_reviewed_at:
            wait_duration = (request.supervisor_reviewed_at - request.created_at).total_seconds()
        event_service.add_audit_trail(
            db=db,
            business_type=models.EventBusinessType.USAGE,
            business_id=request.id,
            business_no=request.request_no,
            action="导师审批通过",
            stage_name="导师审批",
            from_status="supervisor_pending",
            to_status="supervisor_approved",
            operator_id=current_user.id,
            operator_name=current_user.real_name,
            operator_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
            comment=review_in.comment,
            duration_seconds=wait_duration,
            extra_data={"deduct_qty": request.actual_quantity},
        )
        event_service.log_event(
            db=db,
            business_type=models.EventBusinessType.USAGE,
            event_type="supervisor_approved",
            business_id=request.id,
            business_no=request.request_no,
            title=f"导师已通过领用: {request.chemical.name if request.chemical else ''}",
            summary=f"审批人: {current_user.real_name} | 申请人: {request.requester.real_name if request.requester else ''} | 数量: {request.requested_quantity}{request.unit}",
            lab_id=request.lab_id,
            operator_id=current_user.id,
            target_user_id=request.requester_id,
            handle_status=models.EventHandleStatus.COMPLETED,
            detail_url=f"/usage/{request.id}",
            extra_data={"review_comment": review_in.comment},
            emit_ws=False,
        )
    else:
        request.status = models.RequestStatus.SUPERVISOR_REJECTED
        notification_service.create_notification(
            db=db,
            notification_type=models.NotificationType.USAGE_REQUEST,
            title=f"您的领用申请被驳回",
            content=f"申请单号: {request.request_no}, 原因: {review_in.comment or '未给出具体原因'}",
            user_ids=[request.requester_id],
            related_id=request.id,
            related_type="usage_request"
        )
        dispatch_ws_event(
            notification_type="usage",
            event="supervisor_rejected",
            data={
                "id": request.id,
                "request_no": request.request_no,
                "requester_id": request.requester_id,
                "requester_name": request.requester.real_name if request.requester else None,
                "chemical_id": request.chemical_id,
                "chemical_name": request.chemical.name if request.chemical else None,
                "requested_quantity": request.requested_quantity,
                "unit": request.unit,
                "supervisor_id": current_user.id,
                "supervisor_name": current_user.real_name,
                "reject_reason": review_in.comment or "未给出具体原因",
                "status": "supervisor_rejected"
            },
            user_ids=[request.requester_id, current_user.id],
            lab_id=request.lab_id,
            roles=[models.UserRole.SAFETY_OFFICER, models.UserRole.LAB_MANAGER, models.UserRole.SUPERVISOR]
        )
        wait_duration = None
        if request.created_at and request.supervisor_reviewed_at:
            wait_duration = (request.supervisor_reviewed_at - request.created_at).total_seconds()
        event_service.add_audit_trail(
            db=db,
            business_type=models.EventBusinessType.USAGE,
            business_id=request.id,
            business_no=request.request_no,
            action="导师审批拒绝",
            stage_name="导师审批",
            from_status="supervisor_pending",
            to_status="supervisor_rejected",
            operator_id=current_user.id,
            operator_name=current_user.real_name,
            operator_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
            comment=review_in.comment or "未给出具体原因",
            duration_seconds=wait_duration,
        )
        event_service.log_event(
            db=db,
            business_type=models.EventBusinessType.USAGE,
            event_type="supervisor_rejected",
            business_id=request.id,
            business_no=request.request_no,
            title=f"导师已驳回领用: {request.chemical.name if request.chemical else ''}",
            summary=f"审批人: {current_user.real_name} | 原因: {review_in.comment or '未给出具体原因'}",
            lab_id=request.lab_id,
            operator_id=current_user.id,
            target_user_id=request.requester_id,
            handle_status=models.EventHandleStatus.FAILED,
            detail_url=f"/usage/{request.id}",
            extra_data={"reject_reason": review_in.comment},
            emit_ws=False,
        )

    db.commit()
    db.refresh(request)

    return schemas.UsageRequestResponse(
        id=request.id,
        request_no=request.request_no,
        requester_id=request.requester_id,
        requester_name=request.requester.real_name if request.requester else None,
        supervisor_id=request.supervisor_id,
        lab_id=request.lab_id,
        chemical_id=request.chemical_id,
        chemical_name=request.chemical.name if request.chemical else None,
        project_type=request.project_type,
        project_name=request.project_name,
        requested_quantity=request.requested_quantity,
        unit=request.unit,
        purpose=request.purpose,
        status=request.status,
        block_reason=request.block_reason,
        alternative_suggestion=request.alternative_suggestion,
        supervisor_review_comment=request.supervisor_review_comment,
        auto_review_result=request.auto_review_result,
        created_at=request.created_at,
        supervisor_reviewed_at=request.supervisor_reviewed_at,
        completed_at=request.completed_at
    )
