from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Date, Text, ForeignKey, Enum, JSON
from sqlalchemy.orm import relationship
from database import Base
import enum


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    LAB_MANAGER = "lab_manager"
    SAFETY_OFFICER = "safety_officer"
    EMERGENCY_TEAM = "emergency_team"
    SUPERVISOR = "supervisor"
    RESEARCHER = "researcher"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    real_name = Column(String(100), nullable=False)
    email = Column(String(100))
    phone = Column(String(20))
    role = Column(Enum(UserRole), nullable=False)
    lab_id = Column(Integer, ForeignKey("laboratories.id"))
    department = Column(String(100))
    qualification_cert_no = Column(String(100))
    qualification_expire_date = Column(Date)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    lab = relationship("Laboratory", back_populates="users")
    submitted_requests = relationship("UsageRequest", foreign_keys="UsageRequest.requester_id", back_populates="requester")
    approved_requests = relationship("UsageRequest", foreign_keys="UsageRequest.supervisor_id", back_populates="supervisor")
    assigned_alarms = relationship("AlarmTask", back_populates="assignee")
    created_replenishments = relationship("ReplenishmentRequest", foreign_keys="ReplenishmentRequest.created_by_id", back_populates="created_by")
    approved_replenishments_1 = relationship("ReplenishmentRequest", foreign_keys="ReplenishmentRequest.lab_manager_id", back_populates="lab_manager")
    approved_replenishments_2 = relationship("ReplenishmentRequest", foreign_keys="ReplenishmentRequest.safety_officer_id", back_populates="safety_officer")


class Laboratory(Base):
    __tablename__ = "laboratories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    code = Column(String(50), unique=True, nullable=False)
    building = Column(String(100))
    floor = Column(Integer)
    room_no = Column(String(50))
    director = Column(String(100))
    contact_phone = Column(String(20))
    personnel_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    users = relationship("User", back_populates="lab")
    cabinets = relationship("StorageCabinet", back_populates="lab")
    chemicals = relationship("Chemical", back_populates="lab")
    usage_requests = relationship("UsageRequest", back_populates="lab")
    daily_reports = relationship("DailyReport", back_populates="lab")
    sensors = relationship("Sensor", back_populates="lab")


class ChemicalCategory(str, enum.Enum):
    EXPLOSIVE = "explosive"
    FLAMMABLE = "flammable"
    OXIDIZING = "oxidizing"
    TOXIC = "toxic"
    CORROSIVE = "corrosive"
    CARCINOGENIC = "carcinogenic"
    REACTIVE = "reactive"
    GENERAL = "general"


class HazardLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


class Chemical(Base):
    __tablename__ = "chemicals"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    cas_no = Column(String(50), index=True)
    formula = Column(String(100))
    molecular_weight = Column(Float)
    category = Column(Enum(ChemicalCategory), nullable=False)
    hazard_level = Column(Enum(HazardLevel), nullable=False)
    msds_url = Column(String(500))
    msds_data = Column(JSON)
    signal_word = Column(String(20))
    hazard_statements = Column(JSON)
    precautionary_statements = Column(JSON)
    flash_point = Column(Float)
    boiling_point = Column(Float)
    solubility = Column(String(200))
    ppe_required = Column(JSON)
    storage_temp_min = Column(Float)
    storage_temp_max = Column(Float)
    storage_humidity_min = Column(Float)
    storage_humidity_max = Column(Float)
    incompatible_chemicals = Column(JSON)
    emergency_procedure = Column(Text)
    first_aid_measures = Column(Text)
    lab_id = Column(Integer, ForeignKey("laboratories.id"))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    lab = relationship("Laboratory", back_populates="chemicals")
    inventory = relationship("Inventory", back_populates="chemical")
    usage_requests = relationship("UsageRequest", back_populates="chemical")
    waste_records = relationship("WasteRecord", back_populates="chemical")
    replenishments = relationship("ReplenishmentRequest", back_populates="chemical")
    inbound_records = relationship("InboundRecord", back_populates="chemical")


class StorageCabinet(Base):
    __tablename__ = "storage_cabinets"

    id = Column(Integer, primary_key=True, index=True)
    cabinet_no = Column(String(50), unique=True, nullable=False)
    name = Column(String(100))
    lab_id = Column(Integer, ForeignKey("laboratories.id"))
    location = Column(String(200))
    allowed_categories = Column(JSON)
    allowed_hazard_levels = Column(JSON)
    temperature_min = Column(Float)
    temperature_max = Column(Float)
    humidity_min = Column(Float)
    humidity_max = Column(Float)
    has_fire_extinguisher = Column(Boolean, default=False)
    has_ventilation = Column(Boolean, default=False)
    capacity = Column(Float, default=100)
    current_occupancy = Column(Float, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    lab = relationship("Laboratory", back_populates="cabinets")
    inventories = relationship("Inventory", back_populates="cabinet")
    sensors = relationship("Sensor", back_populates="cabinet")


class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)
    chemical_id = Column(Integer, ForeignKey("chemicals.id"), nullable=False)
    cabinet_id = Column(Integer, ForeignKey("storage_cabinets.id"), nullable=False)
    batch_no = Column(String(100), nullable=False)
    quantity = Column(Float, nullable=False)
    unit = Column(String(20), nullable=False)
    current_quantity = Column(Float, nullable=False)
    safety_level = Column(Float, nullable=False)
    manufacturer = Column(String(200))
    production_date = Column(Date)
    expiry_date = Column(Date)
    temp_threshold_min = Column(Float)
    temp_threshold_max = Column(Float)
    humidity_threshold_min = Column(Float)
    humidity_threshold_max = Column(Float)
    status = Column(String(20), default="normal")
    location_tag = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    chemical = relationship("Chemical", back_populates="inventory")
    cabinet = relationship("StorageCabinet", back_populates="inventories")
    inbound_records = relationship("InboundRecord", back_populates="inventory")


class InboundRecord(Base):
    __tablename__ = "inbound_records"

    id = Column(Integer, primary_key=True, index=True)
    chemical_id = Column(Integer, ForeignKey("chemicals.id"), nullable=False)
    inventory_id = Column(Integer, ForeignKey("inventory.id"))
    batch_no = Column(String(100), nullable=False)
    quantity = Column(Float, nullable=False)
    unit = Column(String(20), nullable=False)
    manufacturer = Column(String(200))
    production_date = Column(Date)
    expiry_date = Column(Date)
    msds_verified = Column(Boolean, default=False)
    msds_verify_result = Column(Text)
    cabinet_allocated = Column(Boolean, default=False)
    allocated_cabinet_id = Column(Integer, ForeignKey("storage_cabinets.id"))
    status = Column(String(20), default="pending")
    reject_reason = Column(Text)
    operator_id = Column(Integer, ForeignKey("users.id"))
    admin_notified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime)

    chemical = relationship("Chemical", back_populates="inbound_records")
    inventory = relationship("Inventory", back_populates="inbound_records")


class SensorType(str, enum.Enum):
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    GAS = "gas"
    SMOKE = "smoke"
    PRESSURE = "pressure"


class Sensor(Base):
    __tablename__ = "sensors"

    id = Column(Integer, primary_key=True, index=True)
    sensor_no = Column(String(50), unique=True, nullable=False)
    type = Column(Enum(SensorType), nullable=False)
    gas_type = Column(String(50))
    lab_id = Column(Integer, ForeignKey("laboratories.id"))
    cabinet_id = Column(Integer, ForeignKey("storage_cabinets.id"))
    location = Column(String(200))
    threshold_min = Column(Float)
    threshold_max = Column(Float)
    is_active = Column(Boolean, default=True)
    last_reading = Column(Float)
    last_reading_time = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    lab = relationship("Laboratory", back_populates="sensors")
    cabinet = relationship("StorageCabinet", back_populates="sensors")
    readings = relationship("SensorReading", back_populates="sensor")


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id = Column(Integer, primary_key=True, index=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id"), nullable=False)
    value = Column(Float, nullable=False)
    unit = Column(String(20))
    is_anomaly = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    sensor = relationship("Sensor", back_populates="readings")


class RequestStatus(str, enum.Enum):
    PENDING = "pending"
    AUTO_APPROVED = "auto_approved"
    AUTO_REJECTED = "auto_rejected"
    SUPERVISOR_PENDING = "supervisor_pending"
    SUPERVISOR_APPROVED = "supervisor_approved"
    SUPERVISOR_REJECTED = "supervisor_rejected"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ProjectType(str, enum.Enum):
    ORGANIC_SYNTHESIS = "organic_synthesis"
    INORGANIC_ANALYSIS = "inorganic_analysis"
    BIOCHEMICAL = "biochemical"
    MATERIALS = "materials"
    ENVIRONMENTAL = "environmental"
    GENERAL = "general"


class UsageRequest(Base):
    __tablename__ = "usage_requests"

    id = Column(Integer, primary_key=True, index=True)
    request_no = Column(String(50), unique=True, nullable=False)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    supervisor_id = Column(Integer, ForeignKey("users.id"))
    lab_id = Column(Integer, ForeignKey("laboratories.id"), nullable=False)
    chemical_id = Column(Integer, ForeignKey("chemicals.id"), nullable=False)
    project_type = Column(Enum(ProjectType), nullable=False)
    project_name = Column(String(200))
    requested_quantity = Column(Float, nullable=False)
    unit = Column(String(20), nullable=False)
    purpose = Column(Text)
    qualification_verified = Column(Boolean, default=False)
    qualification_verify_result = Column(Text)
    usage_deviation_checked = Column(Boolean, default=False)
    usage_deviation_ratio = Column(Float)
    auto_review_passed = Column(Boolean, default=True)
    block_reason = Column(Text)
    alternative_suggestion = Column(Text)
    status = Column(Enum(RequestStatus), default=RequestStatus.PENDING)
    auto_review_result = Column(Text)
    supervisor_review_comment = Column(Text)
    actual_quantity = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
    supervisor_reviewed_at = Column(DateTime)
    completed_at = Column(DateTime)

    requester = relationship("User", foreign_keys=[requester_id], back_populates="submitted_requests")
    supervisor = relationship("User", foreign_keys=[supervisor_id], back_populates="approved_requests")
    lab = relationship("Laboratory", back_populates="usage_requests")
    chemical = relationship("Chemical", back_populates="usage_requests")


class AlarmLevel(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class AlarmStatus(str, enum.Enum):
    TRIGGERED = "triggered"
    ACKNOWLEDGED = "acknowledged"
    HANDLING = "handling"
    RESOLVED = "resolved"
    FALSE_ALARM = "false_alarm"


class Alarm(Base):
    __tablename__ = "alarms"

    id = Column(Integer, primary_key=True, index=True)
    alarm_no = Column(String(50), unique=True, nullable=False)
    level = Column(Enum(AlarmLevel), nullable=False)
    type = Column(String(50), nullable=False)
    sensor_id = Column(Integer, ForeignKey("sensors.id"))
    lab_id = Column(Integer, ForeignKey("laboratories.id"))
    cabinet_id = Column(Integer, ForeignKey("storage_cabinets.id"))
    chemical_category = Column(String(50))
    personnel_density = Column(Float)
    trigger_value = Column(Float)
    threshold_value = Column(Float)
    unit = Column(String(20))
    description = Column(Text)
    emergency_plan_id = Column(Integer, ForeignKey("emergency_plans.id"))
    status = Column(Enum(AlarmStatus), default=AlarmStatus.TRIGGERED)
    location = Column(String(200))
    resolution_notes = Column(Text)
    triggered_at = Column(DateTime, default=datetime.utcnow)
    acknowledged_at = Column(DateTime)
    resolved_at = Column(DateTime)

    sensor = relationship("Sensor")
    emergency_plan = relationship("EmergencyPlan", back_populates="alarms")
    tasks = relationship("AlarmTask", back_populates="alarm")
    closure = relationship("AlarmClosure", back_populates="alarm", uselist=False)


class EmergencyPlan(Base):
    __tablename__ = "emergency_plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    code = Column(String(50), unique=True, nullable=False)
    applicable_categories = Column(JSON)
    applicable_hazard_levels = Column(JSON)
    applicable_alarm_levels = Column(JSON)
    min_personnel_density = Column(Float)
    max_personnel_density = Column(Float)
    steps = Column(JSON)
    required_equipment = Column(JSON)
    evacuation_required = Column(Boolean, default=False)
    medical_assistance = Column(Boolean, default=False)
    fire_department = Column(Boolean, default=False)
    priority = Column(Integer, default=10)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    alarms = relationship("Alarm", back_populates="emergency_plan")


class TaskStatus(str, enum.Enum):
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AlarmTask(Base):
    __tablename__ = "alarm_tasks"

    id = Column(Integer, primary_key=True, index=True)
    alarm_id = Column(Integer, ForeignKey("alarms.id"), nullable=False)
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    task_description = Column(Text)
    priority = Column(Integer, default=5)
    status = Column(Enum(TaskStatus), default=TaskStatus.ASSIGNED)
    estimated_distance = Column(Float)
    notes = Column(Text)
    assigned_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    alarm = relationship("Alarm", back_populates="tasks")
    assignee = relationship("User", back_populates="assigned_alarms")
    progress_updates = relationship("AlarmTaskProgress", back_populates="task", cascade="all, delete-orphan")


class WasteStatus(str, enum.Enum):
    PENDING_INSPECTION = "pending_inspection"
    INSPECTION_FAILED = "inspection_failed"
    INSPECTION_PASSED = "inspection_passed"
    BATCHED = "batched"
    IN_TRANSIT = "in_transit"
    DISPOSED = "disposed"


class WasteRecord(Base):
    __tablename__ = "waste_records"

    id = Column(Integer, primary_key=True, index=True)
    waste_no = Column(String(50), unique=True, nullable=False)
    chemical_id = Column(Integer, ForeignKey("chemicals.id"), nullable=False)
    lab_id = Column(Integer, ForeignKey("laboratories.id"))
    waste_type = Column(String(100))
    quantity = Column(Float, nullable=False)
    unit = Column(String(20), nullable=False)
    container_no = Column(String(100))
    container_type = Column(String(100))
    seal_inspection_passed = Column(Boolean, default=False)
    seal_inspection_notes = Column(Text)
    label_inspection_passed = Column(Boolean, default=False)
    label_inspection_notes = Column(Text)
    violation_recorded = Column(Boolean, default=False)
    violation_type = Column(String(100))
    violation_notes = Column(Text)
    status = Column(Enum(WasteStatus), default=WasteStatus.PENDING_INSPECTION)
    batch_id = Column(Integer, ForeignKey("waste_batches.id"))
    disposal_center_id = Column(Integer, ForeignKey("disposal_centers.id"))
    submitter_id = Column(Integer, ForeignKey("users.id"))
    inspector_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    inspected_at = Column(DateTime)

    chemical = relationship("Chemical", back_populates="waste_records")
    batch = relationship("WasteBatch", back_populates="waste_records")
    disposal_center = relationship("DisposalCenter", back_populates="waste_records")


class WasteBatch(Base):
    __tablename__ = "waste_batches"

    id = Column(Integer, primary_key=True, index=True)
    batch_no = Column(String(50), unique=True, nullable=False)
    disposal_center_id = Column(Integer, ForeignKey("disposal_centers.id"), nullable=False)
    transport_company = Column(String(200))
    driver_name = Column(String(100))
    vehicle_plate = Column(String(50))
    manifest_no = Column(String(100))
    total_quantity = Column(Float, default=0)
    status = Column(String(20), default="created")
    created_by_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    shipped_at = Column(DateTime)
    received_at = Column(DateTime)

    waste_records = relationship("WasteRecord", back_populates="batch")
    disposal_center = relationship("DisposalCenter", back_populates="batches")


class DisposalCenter(Base):
    __tablename__ = "disposal_centers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    code = Column(String(50), unique=True, nullable=False)
    address = Column(String(500))
    contact_person = Column(String(100))
    contact_phone = Column(String(20))
    license_no = Column(String(100))
    allowed_waste_types = Column(JSON)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    waste_records = relationship("WasteRecord", back_populates="disposal_center")
    batches = relationship("WasteBatch", back_populates="disposal_center")


class ReplenishmentStatus(str, enum.Enum):
    PENDING_LAB_MANAGER = "pending_lab_manager"
    LAB_MANAGER_APPROVED = "lab_manager_approved"
    LAB_MANAGER_REJECTED = "lab_manager_rejected"
    PENDING_SAFETY = "pending_safety"
    SAFETY_APPROVED = "safety_approved"
    SAFETY_REJECTED = "safety_rejected"
    SYNCED_TO_PURCHASE = "synced_to_purchase"
    CANCELLED = "cancelled"


class ReplenishmentRequest(Base):
    __tablename__ = "replenishment_requests"

    id = Column(Integer, primary_key=True, index=True)
    request_no = Column(String(50), unique=True, nullable=False)
    chemical_id = Column(Integer, ForeignKey("chemicals.id"), nullable=False)
    current_quantity = Column(Float, nullable=False)
    safety_level = Column(Float, nullable=False)
    requested_quantity = Column(Float, nullable=False)
    unit = Column(String(20), nullable=False)
    reason = Column(Text)
    status = Column(Enum(ReplenishmentStatus), default=ReplenishmentStatus.PENDING_LAB_MANAGER)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    lab_manager_id = Column(Integer, ForeignKey("users.id"))
    safety_officer_id = Column(Integer, ForeignKey("users.id"))
    lab_manager_comment = Column(Text)
    safety_officer_comment = Column(Text)
    reminder_sent_count = Column(Integer, default=0)
    last_reminder_sent_at = Column(DateTime)
    purchase_order_no = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    lab_manager_approved_at = Column(DateTime)
    safety_officer_approved_at = Column(DateTime)

    chemical = relationship("Chemical", back_populates="replenishments")
    created_by = relationship("User", foreign_keys=[created_by_id], back_populates="created_replenishments")
    lab_manager = relationship("User", foreign_keys=[lab_manager_id], back_populates="approved_replenishments_1")
    safety_officer = relationship("User", foreign_keys=[safety_officer_id], back_populates="approved_replenishments_2")


class DailyReport(Base):
    __tablename__ = "daily_reports"

    id = Column(Integer, primary_key=True, index=True)
    report_date = Column(Date, nullable=False, index=True)
    lab_id = Column(Integer, ForeignKey("laboratories.id"))
    total_chemical_types = Column(Integer, default=0)
    total_inventory_quantity = Column(Float, default=0)
    consumption_by_category = Column(JSON)
    storage_status_summary = Column(JSON)
    alarm_count_by_level = Column(JSON)
    alarm_count_total = Column(Integer, default=0)
    usage_request_count = Column(Integer, default=0)
    inbound_count = Column(Integer, default=0)
    waste_count = Column(Integer, default=0)
    replenishment_count = Column(Integer, default=0)
    safety_incidents = Column(JSON)
    generated_at = Column(DateTime, default=datetime.utcnow)

    lab = relationship("Laboratory", back_populates="daily_reports")


class NotificationType(str, enum.Enum):
    INBOUND = "inbound"
    USAGE_REQUEST = "usage_request"
    ALARM = "alarm"
    WASTE = "waste"
    REPLENISHMENT = "replenishment"
    SYSTEM = "system"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(Enum(NotificationType), nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text)
    user_id = Column(Integer, ForeignKey("users.id"))
    lab_id = Column(Integer, ForeignKey("laboratories.id"))
    related_id = Column(Integer)
    related_type = Column(String(50))
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")


class EventBusinessType(str, enum.Enum):
    INBOUND = "inbound"
    USAGE = "usage"
    WASTE = "waste"
    ALARM = "alarm"
    REPLENISHMENT = "replenishment"
    SYSTEM = "system"


class EventHandleStatus(str, enum.Enum):
    PENDING = "pending"
    HANDLING = "handling"
    COMPLETED = "completed"
    FAILED = "failed"


class EventLog(Base):
    __tablename__ = "event_logs"

    id = Column(Integer, primary_key=True, index=True)
    event_no = Column(String(50), unique=True, nullable=False, index=True)
    business_type = Column(Enum(EventBusinessType), nullable=False, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    business_id = Column(Integer, nullable=False)
    business_no = Column(String(50), index=True)
    lab_id = Column(Integer, ForeignKey("laboratories.id"))
    operator_id = Column(Integer, ForeignKey("users.id"))
    target_role = Column(String(50))
    target_user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String(300), nullable=False)
    summary = Column(Text)
    handle_status = Column(Enum(EventHandleStatus), default=EventHandleStatus.PENDING, index=True)
    detail_url = Column(String(300))
    extra_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AuditTrail(Base):
    __tablename__ = "audit_trails"

    id = Column(Integer, primary_key=True, index=True)
    business_type = Column(Enum(EventBusinessType), nullable=False, index=True)
    business_id = Column(Integer, nullable=False, index=True)
    business_no = Column(String(50))
    action = Column(String(100), nullable=False)
    stage_name = Column(String(100))
    from_status = Column(String(50))
    to_status = Column(String(50))
    operator_id = Column(Integer, ForeignKey("users.id"))
    operator_name = Column(String(100))
    operator_role = Column(String(50))
    comment = Column(Text)
    duration_seconds = Column(Float)
    extra_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AlarmTaskProgress(Base):
    __tablename__ = "alarm_task_progresses"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("alarm_tasks.id"), nullable=False)
    operator_id = Column(Integer, ForeignKey("users.id"))
    operator_name = Column(String(100))
    progress_status = Column(String(50), nullable=False)
    progress_percent = Column(Integer, default=0)
    description = Column(Text)
    evidence_url = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("AlarmTask", back_populates="progress_updates")


class AlarmClosure(Base):
    __tablename__ = "alarm_closures"

    id = Column(Integer, primary_key=True, index=True)
    alarm_id = Column(Integer, ForeignKey("alarms.id"), nullable=False)
    closed_by_id = Column(Integer, ForeignKey("users.id"))
    closed_by_name = Column(String(100))
    root_cause = Column(Text)
    handling_summary = Column(Text)
    lessons_learned = Column(Text)
    improvement_actions = Column(JSON)
    effectiveness_rating = Column(Integer)
    verified_by_id = Column(Integer, ForeignKey("users.id"))
    verified_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    alarm = relationship("Alarm", back_populates="closure")
