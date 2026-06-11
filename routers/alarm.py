from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
from database import get_db
from auth import get_current_user, require_roles, generate_request_no
from notification_service import notification_service
import models
import schemas

from routers.websocket import dispatch_ws_event
from event_service import event_service

router_sensors = APIRouter(prefix="/api/sensors", tags=["传感器管理"])
router_alarms = APIRouter(prefix="/api/alarms", tags=["告警与应急调度"])


@router_sensors.post("", response_model=schemas.SensorResponse, dependencies=[Depends(require_roles(models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER))])
def create_sensor(sensor_in: schemas.SensorCreate, db: Session = Depends(get_db)):
    if db.query(models.Sensor).filter(models.Sensor.sensor_no == sensor_in.sensor_no).first():
        raise HTTPException(status_code=400, detail="传感器编号已存在")
    sensor = models.Sensor(**sensor_in.model_dump())
    db.add(sensor)
    db.commit()
    db.refresh(sensor)
    return sensor


@router_sensors.get("", response_model=List[schemas.SensorResponse])
def list_sensors(
    type: Optional[str] = None,
    lab_id: Optional[int] = None,
    cabinet_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.Sensor).filter(models.Sensor.is_active == True)
    if type:
        query = query.filter(models.Sensor.type == type)
    if lab_id:
        query = query.filter(models.Sensor.lab_id == lab_id)
    if cabinet_id:
        query = query.filter(models.Sensor.cabinet_id == cabinet_id)
    return query.offset(skip).limit(limit).all()


@router_sensors.post("/readings", response_model=schemas.SensorReadingResponse)
def create_sensor_reading(
    reading_in: schemas.SensorReadingCreate,
    db: Session = Depends(get_db)
):
    sensor = db.query(models.Sensor).filter(models.Sensor.id == reading_in.sensor_id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail="传感器不存在")

    is_anomaly = False
    if sensor.threshold_min is not None and reading_in.value < sensor.threshold_min:
        is_anomaly = True
    if sensor.threshold_max is not None and reading_in.value > sensor.threshold_max:
        is_anomaly = True

    reading = models.SensorReading(
        sensor_id=reading_in.sensor_id,
        value=reading_in.value,
        unit=reading_in.unit,
        is_anomaly=is_anomaly,
        created_at=datetime.utcnow()
    )
    db.add(reading)
    db.flush()

    sensor.last_reading = reading_in.value
    sensor.last_reading_time = reading.created_at
    db.flush()

    if is_anomaly:
        alarm_id = trigger_alarm_from_sensor(db, sensor, reading_in.value, reading_in.unit)
        reading.id = reading.id

    db.commit()
    db.refresh(reading)
    return reading


@router_sensors.get("/{sensor_id}/readings", response_model=List[schemas.SensorReadingResponse])
def get_sensor_readings(
    sensor_id: int,
    hours: int = 24,
    skip: int = 0,
    limit: int = 1000,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    sensor = db.query(models.Sensor).filter(models.Sensor.id == sensor_id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail="传感器不存在")
    since = datetime.utcnow() - timedelta(hours=hours)
    return db.query(models.SensorReading).filter(
        models.SensorReading.sensor_id == sensor_id,
        models.SensorReading.created_at >= since
    ).order_by(models.SensorReading.created_at.desc()).offset(skip).limit(limit).all()


def determine_alarm_level(sensor_type: models.SensorType, value: float, threshold_min: Optional[float], threshold_max: Optional[float]) -> models.AlarmLevel:
    if threshold_max is not None:
        ratio = value / threshold_max if threshold_max > 0 else 1
        if ratio >= 2.0:
            return models.AlarmLevel.EMERGENCY
        elif ratio >= 1.5:
            return models.AlarmLevel.CRITICAL
        elif ratio >= 1.2:
            return models.AlarmLevel.WARNING
        else:
            return models.AlarmLevel.INFO
    if threshold_min is not None and value < threshold_min:
        diff_ratio = (threshold_min - value) / threshold_min if threshold_min > 0 else 0
        if diff_ratio >= 0.5:
            return models.AlarmLevel.CRITICAL
        elif diff_ratio >= 0.2:
            return models.AlarmLevel.WARNING
        return models.AlarmLevel.INFO
    return models.AlarmLevel.WARNING


def get_chemical_category_for_location(db: Session, lab_id: Optional[int], cabinet_id: Optional[int]) -> Optional[str]:
    if cabinet_id:
        inventories = db.query(models.Inventory).filter(models.Inventory.cabinet_id == cabinet_id).all()
        if inventories:
            categories = set(inv.chemical.category.value for inv in inventories if inv.chemical)
            if categories:
                return list(categories)[0]
    if lab_id:
        inventories = db.query(models.Inventory).join(models.StorageCabinet).filter(
            models.StorageCabinet.lab_id == lab_id
        ).all()
        if inventories:
            categories = [inv.chemical.category.value for inv in inventories if inv.chemical]
            if categories:
                from collections import Counter
                return Counter(categories).most_common(1)[0][0]
    return None


def match_emergency_plan(db: Session, chemical_category: Optional[str], hazard_level: Optional[str], alarm_level: models.AlarmLevel, personnel_density: Optional[float]) -> Optional[models.EmergencyPlan]:
    plans = db.query(models.EmergencyPlan).filter(models.EmergencyPlan.is_active == True).all()
    if not plans:
        return None

    alarm_str = alarm_level.value if hasattr(alarm_level, 'value') else str(alarm_level)

    scored = []
    for plan in plans:
        score = 0

        if plan.applicable_alarm_levels and alarm_str in plan.applicable_alarm_levels:
            score += 40

        if plan.applicable_categories and chemical_category:
            if chemical_category in plan.applicable_categories:
                score += 30

        if plan.applicable_hazard_levels and hazard_level:
            if hazard_level in plan.applicable_hazard_levels:
                score += 20

        if personnel_density is not None:
            if plan.min_personnel_density is not None and personnel_density < plan.min_personnel_density:
                continue
            if plan.max_personnel_density is not None and personnel_density > plan.max_personnel_density:
                continue

        score += (100 - plan.priority)

        if score > 0:
            scored.append((plan, score))

    if not scored:
        default = db.query(models.EmergencyPlan).filter(
            models.EmergencyPlan.is_active == True
        ).order_by(models.EmergencyPlan.priority.asc()).first()
        return default

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0]


def assign_emergency_tasks(db: Session, alarm: models.Alarm, plan: models.EmergencyPlan):
    emergency_team_members = db.query(models.User).filter(
        models.User.role == models.UserRole.EMERGENCY_TEAM,
        models.User.is_active == True
    ).all()

    if not emergency_team_members:
        emergency_team_members = db.query(models.User).filter(
            models.User.role.in_([models.UserRole.SAFETY_OFFICER, models.UserRole.ADMIN]),
            models.User.is_active == True
        ).all()

    if not emergency_team_members:
        return []

    tasks = []
    steps = plan.steps or [{"description": "前往现场查看情况", "priority": 1}]
    for i, step in enumerate(steps[:max(1, len(emergency_team_members))]):
        member = emergency_team_members[i % len(emergency_team_members)]
        task = models.AlarmTask(
            alarm_id=alarm.id,
            assignee_id=member.id,
            task_description=step.get("description", "应急处置任务"),
            priority=step.get("priority", alarm.level.value == "emergency" and 1 or 3),
            status=models.TaskStatus.ASSIGNED,
            estimated_distance=None,
            assigned_at=datetime.utcnow()
        )
        db.add(task)
        tasks.append(task)

    return tasks


def trigger_alarm_from_sensor(db: Session, sensor: models.Sensor, value: float, unit: Optional[str]) -> Optional[int]:
    alarm_level = determine_alarm_level(sensor.type, value, sensor.threshold_min, sensor.threshold_max)

    lab_id = sensor.lab_id
    cabinet_id = sensor.cabinet_id
    chemical_category = get_chemical_category_for_location(db, lab_id, cabinet_id)

    personnel_density = None
    if lab_id:
        lab = db.query(models.Laboratory).filter(models.Laboratory.id == lab_id).first()
        if lab and lab.personnel_count:
            personnel_density = float(lab.personnel_count)

    hazard_level = None
    if cabinet_id:
        inventories = db.query(models.Inventory).filter(models.Inventory.cabinet_id == cabinet_id).all()
        if inventories:
            hazard_levels = [inv.chemical.hazard_level.value for inv in inventories if inv.chemical]
            if hazard_levels:
                from collections import Counter
                hazard_level = Counter(hazard_levels).most_common(1)[0][0]

    plan = match_emergency_plan(db, chemical_category, hazard_level, alarm_level, personnel_density)

    type_names = {
        models.SensorType.TEMPERATURE: "温度异常",
        models.SensorType.HUMIDITY: "湿度异常",
        models.SensorType.GAS: f"{sensor.gas_type or '气体'}浓度超标",
        models.SensorType.SMOKE: "烟雾浓度超标",
        models.SensorType.PRESSURE: "压力异常"
    }
    alarm_type = type_names.get(sensor.type, "传感器异常")

    desc_parts = [
        f"传感器[{sensor.sensor_no}]检测到{alarm_type}",
        f"当前值: {value}{unit or ''}",
    ]
    if sensor.threshold_min is not None:
        desc_parts.append(f"阈值下限: {sensor.threshold_min}")
    if sensor.threshold_max is not None:
        desc_parts.append(f"阈值上限: {sensor.threshold_max}")
    if chemical_category:
        desc_parts.append(f"涉及化学品类别: {chemical_category}")
    if personnel_density is not None:
        desc_parts.append(f"区域人员密度: {personnel_density}人")

    alarm = models.Alarm(
        alarm_no=generate_request_no("AL"),
        level=alarm_level,
        type=alarm_type,
        sensor_id=sensor.id,
        lab_id=lab_id,
        cabinet_id=cabinet_id,
        chemical_category=chemical_category,
        personnel_density=personnel_density,
        trigger_value=value,
        threshold_value=sensor.threshold_max or sensor.threshold_min,
        unit=unit,
        description=" | ".join(desc_parts),
        emergency_plan_id=plan.id if plan else None,
        status=models.AlarmStatus.TRIGGERED,
        location=sensor.location,
        triggered_at=datetime.utcnow()
    )
    db.add(alarm)
    db.flush()

    tasks = assign_emergency_tasks(db, alarm, plan) if plan else []

    roles_to_notify = [models.UserRole.EMERGENCY_TEAM, models.UserRole.SAFETY_OFFICER]
    if alarm_level in [models.AlarmLevel.CRITICAL, models.AlarmLevel.EMERGENCY]:
        roles_to_notify.extend([models.UserRole.ADMIN, models.UserRole.LAB_MANAGER])

    level_names = {
        models.AlarmLevel.INFO: "提示",
        models.AlarmLevel.WARNING: "警告",
        models.AlarmLevel.CRITICAL: "严重",
        models.AlarmLevel.EMERGENCY: "紧急"
    }
    level_name = level_names.get(alarm_level, str(alarm_level))

    notification_service.create_notification(
        db=db,
        notification_type=models.NotificationType.ALARM,
        title=f"【{level_name}】{alarm_type}",
        content=f"告警编号: {alarm.alarm_no} | 位置: {sensor.location or '未知'} | {', '.join(desc_parts[:3])}",
        roles=roles_to_notify,
        lab_id=lab_id,
        related_id=alarm.id,
        related_type="alarm"
    )

    task_list = []
    for t in tasks:
        task_list.append({
            "id": t.id,
            "assignee_id": t.assignee_id,
            "assignee_name": t.assignee.real_name if hasattr(t, 'assignee') and t.assignee else None,
            "task_description": t.task_description,
            "priority": t.priority,
            "status": t.status.value if hasattr(t.status, 'value') else str(t.status)
        })

    dispatch_ws_event(
        notification_type="alarm",
        event="triggered",
        data={
            "id": alarm.id,
            "alarm_no": alarm.alarm_no,
            "level": alarm_level.value if hasattr(alarm_level, 'value') else str(alarm_level),
            "level_name": level_name,
            "type": alarm_type,
            "sensor_id": sensor.id,
            "sensor_no": sensor.sensor_no,
            "lab_id": lab_id,
            "cabinet_id": cabinet_id,
            "location": sensor.location,
            "trigger_value": value,
            "threshold_value": sensor.threshold_max or sensor.threshold_min,
            "unit": unit,
            "chemical_category": chemical_category,
            "personnel_density": personnel_density,
            "emergency_plan_id": plan.id if plan else None,
            "emergency_plan_name": plan.name if plan else None,
            "tasks": task_list,
            "description": alarm.description,
            "status": "triggered"
        },
        lab_id=lab_id,
        roles=roles_to_notify + [models.UserRole.SUPERVISOR, models.UserRole.RESEARCHER]
    )

    event_service.add_audit_trail(
        db=db,
        business_type=models.EventBusinessType.ALARM,
        business_id=alarm.id,
        business_no=alarm.alarm_no,
        action="告警触发",
        stage_name=f"传感器异常→{alarm_level.value if hasattr(alarm_level, 'value') else str(alarm_level)}级告警",
        from_status="none",
        to_status="triggered",
        operator_id=None,
        operator_name="传感器",
        operator_role="sensor",
        comment=alarm.description,
        extra_data={
            "trigger_value": value,
            "threshold": sensor.threshold_max or sensor.threshold_min,
            "tasks_count": len(task_list),
        },
    )
    event_service.log_event(
        db=db,
        business_type=models.EventBusinessType.ALARM,
        event_type="triggered",
        business_id=alarm.id,
        business_no=alarm.alarm_no,
        title=f"【{level_name}】{alarm_type}",
        summary=alarm.description,
        lab_id=lab_id,
        target_role=models.UserRole.EMERGENCY_TEAM.value,
        handle_status=models.EventHandleStatus.PENDING,
        detail_url=f"/alarm/{alarm.id}",
        extra_data={
            "level": alarm_level.value if hasattr(alarm_level, 'value') else str(alarm_level),
            "tasks_count": len(task_list),
            "emergency_plan": plan.name if plan else None,
        },
        emit_ws=False,
    )

    return alarm.id


@router_alarms.get("", response_model=List[schemas.AlarmResponse])
def list_alarms(
    level: Optional[str] = None,
    status: Optional[str] = None,
    lab_id: Optional[int] = None,
    hours: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.Alarm)
    if level:
        query = query.filter(models.Alarm.level == level)
    if status:
        query = query.filter(models.Alarm.status == status)
    if lab_id:
        query = query.filter(models.Alarm.lab_id == lab_id)
    if hours:
        since = datetime.utcnow() - timedelta(hours=hours)
        query = query.filter(models.Alarm.triggered_at >= since)

    alarms = query.order_by(models.Alarm.triggered_at.desc()).offset(skip).limit(limit).all()

    responses = []
    for alarm in alarms:
        responses.append(schemas.AlarmResponse(
            id=alarm.id,
            alarm_no=alarm.alarm_no,
            level=alarm.level,
            type=alarm.type,
            sensor_id=alarm.sensor_id,
            lab_id=alarm.lab_id,
            cabinet_id=alarm.cabinet_id,
            chemical_category=alarm.chemical_category,
            personnel_density=alarm.personnel_density,
            trigger_value=alarm.trigger_value,
            threshold_value=alarm.threshold_value,
            unit=alarm.unit,
            description=alarm.description,
            emergency_plan_id=alarm.emergency_plan_id,
            emergency_plan=schemas.EmergencyPlanResponse(
                id=alarm.emergency_plan.id,
                name=alarm.emergency_plan.name,
                code=alarm.emergency_plan.code,
                applicable_categories=alarm.emergency_plan.applicable_categories or [],
                applicable_hazard_levels=alarm.emergency_plan.applicable_hazard_levels or [],
                applicable_alarm_levels=alarm.emergency_plan.applicable_alarm_levels or [],
                min_personnel_density=alarm.emergency_plan.min_personnel_density,
                max_personnel_density=alarm.emergency_plan.max_personnel_density,
                steps=alarm.emergency_plan.steps or [],
                required_equipment=alarm.emergency_plan.required_equipment or [],
                evacuation_required=alarm.emergency_plan.evacuation_required,
                medical_assistance=alarm.emergency_plan.medical_assistance,
                fire_department=alarm.emergency_plan.fire_department,
                priority=alarm.emergency_plan.priority,
                is_active=alarm.emergency_plan.is_active,
                created_at=alarm.emergency_plan.created_at
            ) if alarm.emergency_plan else None,
            status=alarm.status,
            location=alarm.location,
            resolution_notes=alarm.resolution_notes,
            triggered_at=alarm.triggered_at,
            acknowledged_at=alarm.acknowledged_at,
            resolved_at=alarm.resolved_at,
            tasks=[
                schemas.AlarmTaskResponse(
                    id=t.id,
                    alarm_id=t.alarm_id,
                    assignee_id=t.assignee_id,
                    assignee_name=t.assignee.real_name if t.assignee else None,
                    task_description=t.task_description,
                    priority=t.priority,
                    status=t.status,
                    estimated_distance=t.estimated_distance,
                    notes=t.notes,
                    assigned_at=t.assigned_at,
                    started_at=t.started_at,
                    completed_at=t.completed_at
                ) for t in alarm.tasks
            ]
        ))
    return responses


@router_alarms.get("/{alarm_id}", response_model=schemas.AlarmResponse)
def get_alarm(alarm_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    alarm = db.query(models.Alarm).filter(models.Alarm.id == alarm_id).first()
    if not alarm:
        raise HTTPException(status_code=404, detail="告警不存在")

    return schemas.AlarmResponse(
        id=alarm.id,
        alarm_no=alarm.alarm_no,
        level=alarm.level,
        type=alarm.type,
        sensor_id=alarm.sensor_id,
        lab_id=alarm.lab_id,
        cabinet_id=alarm.cabinet_id,
        chemical_category=alarm.chemical_category,
        personnel_density=alarm.personnel_density,
        trigger_value=alarm.trigger_value,
        threshold_value=alarm.threshold_value,
        unit=alarm.unit,
        description=alarm.description,
        emergency_plan_id=alarm.emergency_plan_id,
        emergency_plan=schemas.EmergencyPlanResponse(
            id=alarm.emergency_plan.id,
            name=alarm.emergency_plan.name,
            code=alarm.emergency_plan.code,
            applicable_categories=alarm.emergency_plan.applicable_categories or [],
            applicable_hazard_levels=alarm.emergency_plan.applicable_hazard_levels or [],
            applicable_alarm_levels=alarm.emergency_plan.applicable_alarm_levels or [],
            min_personnel_density=alarm.emergency_plan.min_personnel_density,
            max_personnel_density=alarm.emergency_plan.max_personnel_density,
            steps=alarm.emergency_plan.steps or [],
            required_equipment=alarm.emergency_plan.required_equipment or [],
            evacuation_required=alarm.emergency_plan.evacuation_required,
            medical_assistance=alarm.emergency_plan.medical_assistance,
            fire_department=alarm.emergency_plan.fire_department,
            priority=alarm.emergency_plan.priority,
            is_active=alarm.emergency_plan.is_active,
            created_at=alarm.emergency_plan.created_at
        ) if alarm.emergency_plan else None,
        status=alarm.status,
        location=alarm.location,
        resolution_notes=alarm.resolution_notes,
        triggered_at=alarm.triggered_at,
        acknowledged_at=alarm.acknowledged_at,
        resolved_at=alarm.resolved_at,
        tasks=[
            schemas.AlarmTaskResponse(
                id=t.id,
                alarm_id=t.alarm_id,
                assignee_id=t.assignee_id,
                assignee_name=t.assignee.real_name if t.assignee else None,
                task_description=t.task_description,
                priority=t.priority,
                status=t.status,
                estimated_distance=t.estimated_distance,
                notes=t.notes,
                assigned_at=t.assigned_at,
                started_at=t.started_at,
                completed_at=t.completed_at
            ) for t in alarm.tasks
        ]
    )


@router_alarms.put("/{alarm_id}", response_model=schemas.AlarmResponse)
def update_alarm(
    alarm_id: int,
    update_in: schemas.AlarmUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(models.UserRole.EMERGENCY_TEAM, models.UserRole.SAFETY_OFFICER, models.UserRole.ADMIN))
):
    alarm = db.query(models.Alarm).filter(models.Alarm.id == alarm_id).first()
    if not alarm:
        raise HTTPException(status_code=404, detail="告警不存在")

    old_status = alarm.status.value if hasattr(alarm.status, 'value') else str(alarm.status)
    status_changed = update_in.status and update_in.status != alarm.status

    stage_map = {
        "triggered→acknowledged": "告警触发→应急人员已接单确认",
        "acknowledged→handling": "接单确认→现场处置中",
        "handling→resolved": "处置中→告警解决",
        "triggered→handling": "告警触发→直接进入处置",
        "triggered→resolved": "告警触发→直接解决",
        "triggered→false_alarm": "告警触发→误报标记",
        "acknowledged→resolved": "接单确认→告警解决",
        "handling→false_alarm": "处置中→误报标记",
    }
    default_stage = f"{old_status}→{update_in.status.value if hasattr(update_in.status, 'value') else str(update_in.status)}" if status_changed else None

    if update_in.status == models.AlarmStatus.ACKNOWLEDGED and alarm.status == models.AlarmStatus.TRIGGERED:
        alarm.acknowledged_at = datetime.utcnow()
    if update_in.status in [models.AlarmStatus.RESOLVED, models.AlarmStatus.FALSE_ALARM]:
        alarm.resolved_at = datetime.utcnow()

    if update_in.status:
        alarm.status = update_in.status
    if update_in.resolution_notes:
        alarm.resolution_notes = update_in.resolution_notes

    db.flush()

    if status_changed:
        new_status_val = update_in.status.value if hasattr(update_in.status, 'value') else str(update_in.status)
        stage_key = f"{old_status}→{new_status_val}"
        stage_name = stage_map.get(stage_key, default_stage or stage_key)

        action_names = {
            "acknowledged": "告警确认",
            "handling": "开始处置",
            "resolved": "告警解决",
            "false_alarm": "标记误报"
        }
        action = action_names.get(new_status_val, "状态更新")

        event_status_map = {
            "acknowledged": models.EventHandleStatus.HANDLING,
            "handling": models.EventHandleStatus.HANDLING,
            "resolved": models.EventHandleStatus.COMPLETED,
            "false_alarm": models.EventHandleStatus.COMPLETED,
        }
        ev_handle_status = event_status_map.get(new_status_val, models.EventHandleStatus.HANDLING)

        wait_duration = None
        if alarm.acknowledged_at and old_status == "triggered" and new_status_val == "acknowledged":
            wait_duration = int((alarm.acknowledged_at - alarm.triggered_at).total_seconds())
        elif alarm.resolved_at and new_status_val in ["resolved", "false_alarm"]:
            wait_duration = int((alarm.resolved_at - alarm.triggered_at).total_seconds())

        event_service.add_audit_trail(
            db=db,
            business_type=models.EventBusinessType.ALARM,
            business_id=alarm.id,
            business_no=alarm.alarm_no,
            action=action,
            stage_name=stage_name,
            from_status=old_status,
            to_status=new_status_val,
            operator_id=current_user.id,
            operator_name=current_user.real_name,
            operator_role=current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role),
            comment=update_in.resolution_notes,
            duration_seconds=wait_duration,
            extra_data={
                "old_status": old_status,
                "new_status": new_status_val,
            }
        )

        roles_to_notify = [models.UserRole.EMERGENCY_TEAM, models.UserRole.SAFETY_OFFICER]
        if alarm.level in [models.AlarmLevel.CRITICAL, models.AlarmLevel.EMERGENCY]:
            roles_to_notify.extend([models.UserRole.ADMIN, models.UserRole.LAB_MANAGER])

        level_names = {
            models.AlarmLevel.INFO: "提示",
            models.AlarmLevel.WARNING: "警告",
            models.AlarmLevel.CRITICAL: "严重",
            models.AlarmLevel.EMERGENCY: "紧急"
        }
        level_name = level_names.get(alarm.level, str(alarm.level))

        dispatch_ws_event(
            notification_type="alarm",
            event="status_changed",
            data={
                "id": alarm.id,
                "alarm_no": alarm.alarm_no,
                "business_no": alarm.alarm_no,
                "business_type": "alarm",
                "level": alarm.level.value if hasattr(alarm.level, 'value') else str(alarm.level),
                "level_name": level_name,
                "type": alarm.type,
                "lab_id": alarm.lab_id,
                "cabinet_id": alarm.cabinet_id,
                "location": alarm.location,
                "old_status": old_status,
                "status": new_status_val,
                "operator_id": current_user.id,
                "operator_name": current_user.real_name,
                "resolution_notes": update_in.resolution_notes,
            },
            lab_id=alarm.lab_id,
            roles=roles_to_notify + [models.UserRole.SUPERVISOR, models.UserRole.RESEARCHER],
            user_ids=None,
        )

        event_service.update_event_handle_status(
            db=db,
            business_type=models.EventBusinessType.ALARM,
            business_id=alarm.id,
            new_handle_status=ev_handle_status,
            extra_update={
                "operator_id": current_user.id,
                "summary": f"{action}: {update_in.resolution_notes or alarm.type}",
            }
        )

    db.commit()
    db.refresh(alarm)
    return get_alarm(alarm_id, db, current_user)


@router_alarms.put("/tasks/{task_id}", response_model=schemas.AlarmTaskResponse)
def update_alarm_task(
    task_id: int,
    update_in: schemas.AlarmTaskUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    task = db.query(models.AlarmTask).filter(models.AlarmTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if current_user.role not in [models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER] and task.assignee_id != current_user.id:
        raise HTTPException(status_code=403, detail="只能处理分配给自己的任务")

    old_status = task.status.value if hasattr(task.status, 'value') else str(task.status)
    status_changed = update_in.status and update_in.status != task.status

    if update_in.status == models.TaskStatus.IN_PROGRESS and task.status == models.TaskStatus.ASSIGNED:
        task.started_at = datetime.utcnow()
    if update_in.status == models.TaskStatus.COMPLETED:
        task.completed_at = datetime.utcnow()

    if update_in.status:
        task.status = update_in.status
    if update_in.notes:
        task.notes = update_in.notes

    db.flush()

    if status_changed:
        alarm = task.alarm
        new_status_val = update_in.status.value if hasattr(update_in.status, 'value') else str(update_in.status)

        task_stage_map = {
            "assigned→in_progress": "任务待领取→处置中",
            "in_progress→completed": "处置中→任务完成",
            "assigned→completed": "任务待领取→直接完成",
            "assigned→cancelled": "任务待领取→取消",
            "in_progress→cancelled": "处置中→取消",
        }
        stage_key = f"{old_status}→{new_status_val}"
        stage_name = task_stage_map.get(stage_key, stage_key)

        task_action_map = {
            "in_progress": "开始处置任务",
            "completed": "完成处置任务",
            "cancelled": "取消处置任务",
        }
        action = task_action_map.get(new_status_val, "任务状态更新")

        wait_duration = None
        if task.started_at and old_status == "assigned" and new_status_val == "in_progress":
            wait_duration = int((task.started_at - task.assigned_at).total_seconds())
        elif task.completed_at and new_status_val == "completed":
            wait_duration = int((task.completed_at - task.assigned_at).total_seconds())

        event_service.add_audit_trail(
            db=db,
            business_type=models.EventBusinessType.ALARM,
            business_id=task.alarm_id,
            business_no=alarm.alarm_no if alarm else None,
            action=action,
            stage_name=f"[{task.task_description[:30]}] {stage_name}",
            from_status=old_status,
            to_status=new_status_val,
            operator_id=current_user.id,
            operator_name=current_user.real_name,
            operator_role=current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role),
            comment=update_in.notes,
            duration_seconds=wait_duration,
            extra_data={
                "task_id": task.id,
                "task_desc": task.task_description,
                "old_status": old_status,
                "new_status": new_status_val,
            }
        )

        roles_to_notify = [models.UserRole.EMERGENCY_TEAM, models.UserRole.SAFETY_OFFICER]
        if alarm and alarm.level in [models.AlarmLevel.CRITICAL, models.AlarmLevel.EMERGENCY]:
            roles_to_notify.extend([models.UserRole.ADMIN, models.UserRole.LAB_MANAGER])

        if alarm:
            level_names = {
                models.AlarmLevel.INFO: "提示",
                models.AlarmLevel.WARNING: "警告",
                models.AlarmLevel.CRITICAL: "严重",
                models.AlarmLevel.EMERGENCY: "紧急"
            }
            level_name = level_names.get(alarm.level, str(alarm.level))

            dispatch_ws_event(
                notification_type="alarm",
                event="task_status_changed",
                data={
                    "task_id": task.id,
                    "alarm_id": task.alarm_id,
                    "alarm_no": alarm.alarm_no,
                    "business_no": alarm.alarm_no,
                    "business_type": "alarm",
                    "level": alarm.level.value if hasattr(alarm.level, 'value') else str(alarm.level),
                    "level_name": level_name,
                    "type": alarm.type,
                    "lab_id": alarm.lab_id,
                    "location": alarm.location,
                    "task_description": task.task_description,
                    "old_status": old_status,
                    "status": new_status_val,
                    "operator_id": current_user.id,
                    "operator_name": current_user.real_name,
                    "notes": update_in.notes,
                },
                lab_id=alarm.lab_id,
                roles=roles_to_notify + [models.UserRole.SUPERVISOR, models.UserRole.RESEARCHER],
                user_ids=[task.assignee_id] if task.assignee_id else None,
            )

    db.commit()
    db.refresh(task)

    return schemas.AlarmTaskResponse(
        id=task.id,
        alarm_id=task.alarm_id,
        assignee_id=task.assignee_id,
        assignee_name=task.assignee.real_name if task.assignee else None,
        task_description=task.task_description,
        priority=task.priority,
        status=task.status,
        estimated_distance=task.estimated_distance,
        notes=task.notes,
        assigned_at=task.assigned_at,
        started_at=task.started_at,
        completed_at=task.completed_at
    )


@router_alarms.get("/tasks/mine", response_model=List[schemas.AlarmTaskResponse])
def get_my_alarm_tasks(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.AlarmTask).filter(models.AlarmTask.assignee_id == current_user.id)
    if status:
        query = query.filter(models.AlarmTask.status == status)
    tasks = query.order_by(models.AlarmTask.assigned_at.desc()).offset(skip).limit(limit).all()

    return [
        schemas.AlarmTaskResponse(
            id=t.id,
            alarm_id=t.alarm_id,
            assignee_id=t.assignee_id,
            assignee_name=t.assignee.real_name if t.assignee else None,
            task_description=t.task_description,
            priority=t.priority,
            status=t.status,
            estimated_distance=t.estimated_distance,
            notes=t.notes,
            assigned_at=t.assigned_at,
            started_at=t.started_at,
            completed_at=t.completed_at
        ) for t in tasks
    ]


@router_alarms.post("/tasks/{task_id}/accept", response_model=schemas.AlarmTaskResponse)
def accept_alarm_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    task = db.query(models.AlarmTask).filter(models.AlarmTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status not in [models.TaskStatus.ASSIGNED]:
        raise HTTPException(status_code=400, detail=f"当前任务状态为{task.status.value if hasattr(task.status, 'value') else str(task.status)}，无法接单")

    if current_user.role not in [models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER, models.UserRole.EMERGENCY_TEAM]:
        raise HTTPException(status_code=403, detail="没有权限接单")
    if task.assignee_id and task.assignee_id != current_user.id and current_user.role not in [models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER]:
        raise HTTPException(status_code=403, detail="该任务已分配给其他人员")

    old_status = task.status.value if hasattr(task.status, 'value') else str(task.status)
    task.assignee_id = current_user.id
    task.status = models.TaskStatus.IN_PROGRESS
    task.started_at = datetime.utcnow()

    alarm = task.alarm

    wait_duration = int((task.started_at - task.assigned_at).total_seconds()) if task.assigned_at else None
    event_service.add_audit_trail(
        db=db,
        business_type=models.EventBusinessType.ALARM,
        business_id=task.alarm_id,
        business_no=alarm.alarm_no if alarm else None,
        action="应急人员接单",
        stage_name=f"[{task.task_description[:30]}] 任务待领取→处置中",
        from_status=old_status,
        to_status="in_progress",
        operator_id=current_user.id,
        operator_name=current_user.real_name,
        operator_role=current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role),
        comment=f"{current_user.real_name}确认接单并开始处置",
        duration_seconds=wait_duration,
        extra_data={
            "task_id": task.id,
            "task_desc": task.task_description,
            "action_type": "accept",
        }
    )

    if alarm and alarm.status == models.AlarmStatus.TRIGGERED:
        alarm.status = models.AlarmStatus.HANDLING
        alarm.acknowledged_at = task.started_at
        event_service.update_event_handle_status(
            db=db,
            business_type=models.EventBusinessType.ALARM,
            business_id=alarm.id,
            new_handle_status=models.EventHandleStatus.HANDLING,
            extra_update={
                "operator_id": current_user.id,
                "summary": f"应急人员已接单处置: {task.task_description[:30]}",
            }
        )
        event_service.add_audit_trail(
            db=db,
            business_type=models.EventBusinessType.ALARM,
            business_id=alarm.id,
            business_no=alarm.alarm_no,
            action="告警开始处置",
            stage_name="告警触发→现场处置中",
            from_status="triggered",
            to_status="handling",
            operator_id=current_user.id,
            operator_name=current_user.real_name,
            operator_role=current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role),
            comment=f"{current_user.real_name}接单后自动进入处置状态",
            duration_seconds=int((alarm.acknowledged_at - alarm.triggered_at).total_seconds()) if alarm.triggered_at else None,
        )

    db.flush()

    roles_to_notify = [models.UserRole.EMERGENCY_TEAM, models.UserRole.SAFETY_OFFICER]
    if alarm and alarm.level in [models.AlarmLevel.CRITICAL, models.AlarmLevel.EMERGENCY]:
        roles_to_notify.extend([models.UserRole.ADMIN, models.UserRole.LAB_MANAGER])

    if alarm:
        level_names = {
            models.AlarmLevel.INFO: "提示",
            models.AlarmLevel.WARNING: "警告",
            models.AlarmLevel.CRITICAL: "严重",
            models.AlarmLevel.EMERGENCY: "紧急"
        }
        level_name = level_names.get(alarm.level, str(alarm.level))

        dispatch_ws_event(
            notification_type="alarm",
            event="task_accepted",
            data={
                "task_id": task.id,
                "alarm_id": task.alarm_id,
                "alarm_no": alarm.alarm_no,
                "business_no": alarm.alarm_no,
                "business_type": "alarm",
                "level": alarm.level.value if hasattr(alarm.level, 'value') else str(alarm.level),
                "level_name": level_name,
                "type": alarm.type,
                "lab_id": alarm.lab_id,
                "location": alarm.location,
                "alarm_status": alarm.status.value if hasattr(alarm.status, 'value') else str(alarm.status),
                "task_description": task.task_description,
                "task_status": "in_progress",
                "assignee_id": current_user.id,
                "assignee_name": current_user.real_name,
                "operator_id": current_user.id,
                "operator_name": current_user.real_name,
                "started_at": task.started_at.isoformat() if task.started_at else None,
            },
            lab_id=alarm.lab_id,
            roles=roles_to_notify + [models.UserRole.SUPERVISOR, models.UserRole.RESEARCHER],
        )

    db.commit()
    db.refresh(task)

    return schemas.AlarmTaskResponse(
        id=task.id,
        alarm_id=task.alarm_id,
        assignee_id=task.assignee_id,
        assignee_name=task.assignee.real_name if task.assignee else None,
        task_description=task.task_description,
        priority=task.priority,
        status=task.status,
        estimated_distance=task.estimated_distance,
        notes=task.notes,
        assigned_at=task.assigned_at,
        started_at=task.started_at,
        completed_at=task.completed_at
    )


@router_alarms.post("/tasks/{task_id}/progress", response_model=schemas.AlarmTaskProgressResponse)
def add_task_progress(
    task_id: int,
    progress_in: schemas.AlarmTaskProgressCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    task = db.query(models.AlarmTask).filter(models.AlarmTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if current_user.role not in [models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER] and task.assignee_id != current_user.id:
        raise HTTPException(status_code=403, detail="只能更新分配给自己的任务进度")

    if progress_in.progress_percent < 0 or progress_in.progress_percent > 100:
        raise HTTPException(status_code=400, detail="进度百分比必须在0-100之间")

    progress = models.AlarmTaskProgress(
        task_id=task_id,
        operator_id=current_user.id,
        operator_name=current_user.real_name,
        progress_status=progress_in.progress_status,
        progress_percent=progress_in.progress_percent,
        description=progress_in.description,
        evidence_url=progress_in.evidence_url,
        created_at=datetime.utcnow(),
    )
    db.add(progress)
    db.flush()

    if task.status == models.TaskStatus.ASSIGNED and progress_in.progress_percent > 0:
        task.status = models.TaskStatus.IN_PROGRESS
        task.started_at = datetime.utcnow()
        db.flush()

    if progress_in.progress_percent >= 100 and task.status != models.TaskStatus.COMPLETED:
        task.status = models.TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()
        db.flush()

    alarm = task.alarm

    event_service.add_audit_trail(
        db=db,
        business_type=models.EventBusinessType.ALARM,
        business_id=task.alarm_id,
        business_no=alarm.alarm_no if alarm else None,
        action="任务进度更新",
        stage_name=f"[{task.task_description[:30]}] 进度更新至{progress_in.progress_percent}%",
        from_status=task.status.value if hasattr(task.status, 'value') else str(task.status),
        to_status=task.status.value if hasattr(task.status, 'value') else str(task.status),
        operator_id=current_user.id,
        operator_name=current_user.real_name,
        operator_role=current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role),
        comment=progress_in.description or progress_in.progress_status,
        extra_data={
            "task_id": task.id,
            "progress_id": progress.id,
            "progress_percent": progress_in.progress_percent,
            "progress_status": progress_in.progress_status,
            "evidence_url": progress_in.evidence_url,
        }
    )

    roles_to_notify = [models.UserRole.EMERGENCY_TEAM, models.UserRole.SAFETY_OFFICER]
    if alarm and alarm.level in [models.AlarmLevel.CRITICAL, models.AlarmLevel.EMERGENCY]:
        roles_to_notify.extend([models.UserRole.ADMIN, models.UserRole.LAB_MANAGER])

    if alarm:
        level_names = {
            models.AlarmLevel.INFO: "提示",
            models.AlarmLevel.WARNING: "警告",
            models.AlarmLevel.CRITICAL: "严重",
            models.AlarmLevel.EMERGENCY: "紧急"
        }
        level_name = level_names.get(alarm.level, str(alarm.level))

        dispatch_ws_event(
            notification_type="alarm",
            event="task_progress",
            data={
                "progress_id": progress.id,
                "task_id": task.id,
                "alarm_id": task.alarm_id,
                "alarm_no": alarm.alarm_no,
                "business_no": alarm.alarm_no,
                "business_type": "alarm",
                "level": alarm.level.value if hasattr(alarm.level, 'value') else str(alarm.level),
                "level_name": level_name,
                "type": alarm.type,
                "lab_id": alarm.lab_id,
                "location": alarm.location,
                "task_description": task.task_description,
                "task_status": task.status.value if hasattr(task.status, 'value') else str(task.status),
                "progress_percent": progress_in.progress_percent,
                "progress_status": progress_in.progress_status,
                "description": progress_in.description,
                "evidence_url": progress_in.evidence_url,
                "operator_id": current_user.id,
                "operator_name": current_user.real_name,
            },
            lab_id=alarm.lab_id,
            roles=roles_to_notify + [models.UserRole.SUPERVISOR, models.UserRole.RESEARCHER],
            user_ids=[task.assignee_id] if task.assignee_id else None,
        )

    db.commit()
    db.refresh(progress)

    return schemas.AlarmTaskProgressResponse(
        id=progress.id,
        task_id=progress.task_id,
        operator_id=progress.operator_id,
        operator_name=progress.operator_name,
        progress_status=progress.progress_status,
        progress_percent=progress.progress_percent,
        description=progress.description,
        evidence_url=progress.evidence_url,
        created_at=progress.created_at,
    )


@router_alarms.post("/{alarm_id}/closure", response_model=schemas.AlarmClosureResponse)
def close_alarm(
    alarm_id: int,
    closure_in: schemas.AlarmClosureCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(models.UserRole.SAFETY_OFFICER, models.UserRole.ADMIN))
):
    alarm = db.query(models.Alarm).filter(models.Alarm.id == alarm_id).first()
    if not alarm:
        raise HTTPException(status_code=404, detail="告警不存在")

    if alarm.status == models.AlarmStatus.RESOLVED:
        raise HTTPException(status_code=400, detail="该告警已完成复盘")

    existing_closure = db.query(models.AlarmClosure).filter(models.AlarmClosure.alarm_id == alarm_id).first()
    if existing_closure:
        raise HTTPException(status_code=400, detail="该告警已有复盘记录")

    uncompleted_tasks = db.query(models.AlarmTask).filter(
        models.AlarmTask.alarm_id == alarm_id,
        models.AlarmTask.status.notin_([models.TaskStatus.COMPLETED, models.TaskStatus.CANCELLED])
    ).all()
    if uncompleted_tasks and current_user.role != models.UserRole.ADMIN:
        raise HTTPException(
            status_code=400,
            detail=f"尚有{len(uncompleted_tasks)}个处置任务未完成，完成后再进行复盘"
        )

    old_status = alarm.status.value if hasattr(alarm.status, 'value') else str(alarm.status)
    alarm.status = models.AlarmStatus.RESOLVED
    alarm.resolved_at = datetime.utcnow()

    closure = models.AlarmClosure(
        alarm_id=alarm_id,
        closed_by_id=current_user.id,
        closed_by_name=current_user.real_name,
        root_cause=closure_in.root_cause,
        handling_summary=closure_in.handling_summary,
        lessons_learned=closure_in.lessons_learned,
        improvement_actions=closure_in.improvement_actions,
        effectiveness_rating=closure_in.effectiveness_rating,
        created_at=datetime.utcnow(),
    )
    db.add(closure)
    db.flush()

    wait_duration = int((alarm.resolved_at - alarm.triggered_at).total_seconds()) if alarm.triggered_at and alarm.resolved_at else None
    event_service.add_audit_trail(
        db=db,
        business_type=models.EventBusinessType.ALARM,
        business_id=alarm.id,
        business_no=alarm.alarm_no,
        action="告警结束复盘",
        stage_name=f"{old_status}→告警解决(复盘完成)",
        from_status=old_status,
        to_status="resolved",
        operator_id=current_user.id,
        operator_name=current_user.real_name,
        operator_role=current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role),
        comment=f"根因: {closure_in.root_cause} | 处置总结: {closure_in.handling_summary}",
        duration_seconds=wait_duration,
        extra_data={
            "closure_id": closure.id,
            "root_cause": closure_in.root_cause,
            "lessons_learned": closure_in.lessons_learned,
            "improvement_actions": closure_in.improvement_actions,
            "effectiveness_rating": closure_in.effectiveness_rating,
        }
    )

    event_service.update_event_handle_status(
        db=db,
        business_type=models.EventBusinessType.ALARM,
        business_id=alarm.id,
        new_handle_status=models.EventHandleStatus.COMPLETED,
        extra_update={
            "operator_id": current_user.id,
            "summary": f"告警复盘完成: 根因={closure_in.root_cause[:40]}",
        }
    )

    roles_to_notify = [models.UserRole.EMERGENCY_TEAM, models.UserRole.SAFETY_OFFICER]
    if alarm.level in [models.AlarmLevel.CRITICAL, models.AlarmLevel.EMERGENCY]:
        roles_to_notify.extend([models.UserRole.ADMIN, models.UserRole.LAB_MANAGER])

    level_names = {
        models.AlarmLevel.INFO: "提示",
        models.AlarmLevel.WARNING: "警告",
        models.AlarmLevel.CRITICAL: "严重",
        models.AlarmLevel.EMERGENCY: "紧急"
    }
    level_name = level_names.get(alarm.level, str(alarm.level))

    dispatch_ws_event(
        notification_type="alarm",
        event="closed",
        data={
            "closure_id": closure.id,
            "alarm_id": alarm.id,
            "alarm_no": alarm.alarm_no,
            "business_no": alarm.alarm_no,
            "business_type": "alarm",
            "level": alarm.level.value if hasattr(alarm.level, 'value') else str(alarm.level),
            "level_name": level_name,
            "type": alarm.type,
            "lab_id": alarm.lab_id,
            "location": alarm.location,
            "status": "resolved",
            "old_status": old_status,
            "root_cause": closure_in.root_cause,
            "handling_summary": closure_in.handling_summary,
            "lessons_learned": closure_in.lessons_learned,
            "improvement_actions": closure_in.improvement_actions,
            "effectiveness_rating": closure_in.effectiveness_rating,
            "operator_id": current_user.id,
            "operator_name": current_user.real_name,
            "resolved_at": alarm.resolved_at.isoformat() if alarm.resolved_at else None,
        },
        lab_id=alarm.lab_id,
        roles=roles_to_notify + [models.UserRole.SUPERVISOR, models.UserRole.RESEARCHER],
    )

    db.commit()
    db.refresh(closure)

    return schemas.AlarmClosureResponse(
        id=closure.id,
        alarm_id=closure.alarm_id,
        closed_by_id=closure.closed_by_id,
        closed_by_name=closure.closed_by_name,
        root_cause=closure.root_cause,
        handling_summary=closure.handling_summary,
        lessons_learned=closure.lessons_learned,
        improvement_actions=closure.improvement_actions,
        effectiveness_rating=closure.effectiveness_rating,
        verified_by_id=closure.verified_by_id,
        verified_at=closure.verified_at,
        created_at=closure.created_at,
    )


@router_alarms.get("/tasks/{task_id}/detail", response_model=schemas.AlarmTaskDetailResponse)
def get_alarm_task_detail(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    task = db.query(models.AlarmTask).filter(models.AlarmTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    progresses = sorted(task.progress_updates, key=lambda p: p.created_at) if task.progress_updates else []

    return schemas.AlarmTaskDetailResponse(
        id=task.id,
        alarm_id=task.alarm_id,
        assignee_id=task.assignee_id,
        assignee_name=task.assignee.real_name if task.assignee else None,
        task_description=task.task_description,
        priority=task.priority,
        status=task.status,
        estimated_distance=task.estimated_distance,
        notes=task.notes,
        assigned_at=task.assigned_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        progress_updates=[
            schemas.AlarmTaskProgressResponse(
                id=p.id,
                task_id=p.task_id,
                operator_id=p.operator_id,
                operator_name=p.operator_name,
                progress_status=p.progress_status,
                progress_percent=p.progress_percent,
                description=p.description,
                evidence_url=p.evidence_url,
                created_at=p.created_at,
            ) for p in progresses
        ]
    )


@router_alarms.get("/{alarm_id}/detail", response_model=schemas.AlarmDetailResponse)
def get_alarm_detail(
    alarm_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    alarm = db.query(models.Alarm).filter(models.Alarm.id == alarm_id).first()
    if not alarm:
        raise HTTPException(status_code=404, detail="告警不存在")

    basic_resp = get_alarm(alarm_id, db, current_user)
    audit_trails = event_service.get_audit_trails(db, models.EventBusinessType.ALARM, alarm.id)

    return schemas.AlarmDetailResponse(
        **basic_resp.model_dump(),
        closure=schemas.AlarmClosureResponse(
            id=alarm.closure.id,
            alarm_id=alarm.closure.alarm_id,
            closed_by_id=alarm.closure.closed_by_id,
            closed_by_name=alarm.closure.closed_by_name,
            root_cause=alarm.closure.root_cause,
            handling_summary=alarm.closure.handling_summary,
            lessons_learned=alarm.closure.lessons_learned,
            improvement_actions=alarm.closure.improvement_actions,
            effectiveness_rating=alarm.closure.effectiveness_rating,
            verified_by_id=alarm.closure.verified_by_id,
            verified_at=alarm.closure.verified_at,
            created_at=alarm.closure.created_at,
        ) if hasattr(alarm, 'closure') and alarm.closure else None,
        audit_trails=[
            schemas.AuditTrailResponse(
                id=a.id,
                business_type=a.business_type,
                business_id=a.business_id,
                business_no=a.business_no,
                action=a.action,
                stage_name=a.stage_name,
                from_status=a.from_status,
                to_status=a.to_status,
                operator_id=a.operator_id,
                operator_name=a.operator_name,
                operator_role=a.operator_role,
                comment=a.comment,
                duration_seconds=a.duration_seconds,
                extra_data=a.extra_data,
                created_at=a.created_at,
            ) for a in audit_trails
        ]
    )


router_plans = APIRouter(prefix="/api/emergency-plans", tags=["应急预案"])


@router_plans.post("", response_model=schemas.EmergencyPlanResponse, dependencies=[Depends(require_roles(models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER))])
def create_emergency_plan(plan_in: schemas.EmergencyPlanCreate, db: Session = Depends(get_db)):
    if db.query(models.EmergencyPlan).filter(models.EmergencyPlan.code == plan_in.code).first():
        raise HTTPException(status_code=400, detail="预案编码已存在")
    plan = models.EmergencyPlan(**plan_in.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router_plans.get("", response_model=List[schemas.EmergencyPlanResponse])
def list_emergency_plans(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    return db.query(models.EmergencyPlan).filter(models.EmergencyPlan.is_active == True).order_by(models.EmergencyPlan.priority.asc()).offset(skip).limit(limit).all()
