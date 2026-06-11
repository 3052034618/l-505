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

    if update_in.status == models.AlarmStatus.ACKNOWLEDGED and alarm.status == models.AlarmStatus.TRIGGERED:
        alarm.acknowledged_at = datetime.utcnow()
    if update_in.status == models.AlarmStatus.RESOLVED:
        alarm.resolved_at = datetime.utcnow()
        alarm.status = update_in.status

    if update_in.status:
        alarm.status = update_in.status
    if update_in.resolution_notes:
        alarm.resolution_notes = update_in.resolution_notes

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

    if update_in.status == models.TaskStatus.IN_PROGRESS and task.status == models.TaskStatus.ASSIGNED:
        task.started_at = datetime.utcnow()
    if update_in.status == models.TaskStatus.COMPLETED:
        task.completed_at = datetime.utcnow()

    if update_in.status:
        task.status = update_in.status
    if update_in.notes:
        task.notes = update_in.notes

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
