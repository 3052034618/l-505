from datetime import datetime, date
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, EmailStr
from models import (
    UserRole, ChemicalCategory, HazardLevel, SensorType,
    RequestStatus, ProjectType, AlarmLevel, AlarmStatus,
    TaskStatus, WasteStatus, ReplenishmentStatus, NotificationType
)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class UserBase(BaseModel):
    username: str
    real_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    role: UserRole
    lab_id: Optional[int] = None
    department: Optional[str] = None
    qualification_cert_no: Optional[str] = None
    qualification_expire_date: Optional[date] = None


class UserCreate(UserBase):
    password: str = Field(..., min_length=6)


class UserUpdate(BaseModel):
    real_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[UserRole] = None
    lab_id: Optional[int] = None
    department: Optional[str] = None
    qualification_cert_no: Optional[str] = None
    qualification_expire_date: Optional[date] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class UserResponse(UserBase):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class LaboratoryBase(BaseModel):
    name: str
    code: str
    building: Optional[str] = None
    floor: Optional[int] = None
    room_no: Optional[str] = None
    director: Optional[str] = None
    contact_phone: Optional[str] = None
    personnel_count: int = 0


class LaboratoryCreate(LaboratoryBase):
    pass


class LaboratoryResponse(LaboratoryBase):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ChemicalBase(BaseModel):
    name: str
    cas_no: Optional[str] = None
    formula: Optional[str] = None
    molecular_weight: Optional[float] = None
    category: ChemicalCategory
    hazard_level: HazardLevel
    msds_url: Optional[str] = None
    msds_data: Optional[Dict[str, Any]] = None
    signal_word: Optional[str] = None
    hazard_statements: Optional[List[str]] = None
    precautionary_statements: Optional[List[str]] = None
    flash_point: Optional[float] = None
    boiling_point: Optional[float] = None
    solubility: Optional[str] = None
    ppe_required: Optional[List[str]] = None
    storage_temp_min: Optional[float] = None
    storage_temp_max: Optional[float] = None
    storage_humidity_min: Optional[float] = None
    storage_humidity_max: Optional[float] = None
    incompatible_chemicals: Optional[List[str]] = None
    emergency_procedure: Optional[str] = None
    first_aid_measures: Optional[str] = None
    lab_id: Optional[int] = None


class ChemicalCreate(ChemicalBase):
    pass


class ChemicalUpdate(BaseModel):
    name: Optional[str] = None
    cas_no: Optional[str] = None
    category: Optional[ChemicalCategory] = None
    hazard_level: Optional[HazardLevel] = None
    storage_temp_min: Optional[float] = None
    storage_temp_max: Optional[float] = None
    storage_humidity_min: Optional[float] = None
    storage_humidity_max: Optional[float] = None
    incompatible_chemicals: Optional[List[str]] = None
    is_active: Optional[bool] = None


class ChemicalResponse(ChemicalBase):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class StorageCabinetBase(BaseModel):
    cabinet_no: str
    name: Optional[str] = None
    lab_id: int
    location: Optional[str] = None
    allowed_categories: Optional[List[str]] = None
    allowed_hazard_levels: Optional[List[str]] = None
    temperature_min: Optional[float] = None
    temperature_max: Optional[float] = None
    humidity_min: Optional[float] = None
    humidity_max: Optional[float] = None
    has_fire_extinguisher: bool = False
    has_ventilation: bool = False
    capacity: float = 100


class StorageCabinetCreate(StorageCabinetBase):
    pass


class StorageCabinetResponse(StorageCabinetBase):
    id: int
    current_occupancy: float
    is_active: bool

    class Config:
        from_attributes = True


class InventoryBase(BaseModel):
    chemical_id: int
    cabinet_id: int
    batch_no: str
    quantity: float
    unit: str
    safety_level: float
    manufacturer: Optional[str] = None
    production_date: Optional[date] = None
    expiry_date: Optional[date] = None


class InventoryResponse(InventoryBase):
    id: int
    current_quantity: float
    temp_threshold_min: Optional[float] = None
    temp_threshold_max: Optional[float] = None
    humidity_threshold_min: Optional[float] = None
    humidity_threshold_max: Optional[float] = None
    status: str
    created_at: datetime
    chemical: Optional[ChemicalResponse] = None
    cabinet: Optional[StorageCabinetResponse] = None

    class Config:
        from_attributes = True


class InboundRequest(BaseModel):
    chemical_id: int
    batch_no: str
    quantity: float
    unit: str
    manufacturer: Optional[str] = None
    production_date: Optional[date] = None
    expiry_date: Optional[date] = None
    msds_data: Optional[Dict[str, Any]] = None


class CabinetAllocationResult(BaseModel):
    cabinet_id: Optional[int] = None
    cabinet_no: Optional[str] = None
    allocated: bool
    reason: Optional[str] = None
    temp_threshold_min: Optional[float] = None
    temp_threshold_max: Optional[float] = None
    humidity_threshold_min: Optional[float] = None
    humidity_threshold_max: Optional[float] = None


class MsdsVerificationResult(BaseModel):
    verified: bool
    issues: List[str] = []
    warnings: List[str] = []


class InboundResponse(BaseModel):
    id: int
    chemical_id: int
    batch_no: str
    quantity: float
    unit: str
    msds_verified: bool
    msds_verify_result: Optional[str] = None
    cabinet_allocated: bool
    allocated_cabinet_id: Optional[int] = None
    status: str
    reject_reason: Optional[str] = None
    admin_notified: bool
    created_at: datetime
    msds_verification: Optional[MsdsVerificationResult] = None
    cabinet_allocation: Optional[CabinetAllocationResult] = None

    class Config:
        from_attributes = True


class SensorBase(BaseModel):
    sensor_no: str
    type: SensorType
    gas_type: Optional[str] = None
    lab_id: Optional[int] = None
    cabinet_id: Optional[int] = None
    location: Optional[str] = None
    threshold_min: Optional[float] = None
    threshold_max: Optional[float] = None


class SensorCreate(SensorBase):
    pass


class SensorResponse(SensorBase):
    id: int
    is_active: bool
    last_reading: Optional[float] = None
    last_reading_time: Optional[datetime] = None

    class Config:
        from_attributes = True


class SensorReadingCreate(BaseModel):
    sensor_id: int
    value: float
    unit: Optional[str] = None


class SensorReadingResponse(BaseModel):
    id: int
    sensor_id: int
    value: float
    unit: Optional[str] = None
    is_anomaly: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UsageRequestCreate(BaseModel):
    lab_id: int
    chemical_id: int
    project_type: ProjectType
    project_name: Optional[str] = None
    requested_quantity: float
    unit: str
    purpose: Optional[str] = None


class QualificationCheckResult(BaseModel):
    passed: bool
    message: str
    issues: List[str] = []


class UsageDeviationCheckResult(BaseModel):
    passed: bool
    message: str
    deviation_ratio: Optional[float] = None
    historical_average: Optional[float] = None


class AlternativeSuggestion(BaseModel):
    chemical_name: str
    reason: str
    estimated_safety_level: Optional[str] = None


class AutoReviewResult(BaseModel):
    passed: bool
    needs_supervisor_approval: bool
    block_reason: Optional[str] = None
    alternative_suggestions: List[AlternativeSuggestion] = []
    qualification_check: Optional[QualificationCheckResult] = None
    deviation_check: Optional[UsageDeviationCheckResult] = None


class UsageRequestResponse(BaseModel):
    id: int
    request_no: str
    requester_id: int
    requester_name: Optional[str] = None
    supervisor_id: Optional[int] = None
    lab_id: int
    chemical_id: int
    chemical_name: Optional[str] = None
    project_type: ProjectType
    project_name: Optional[str] = None
    requested_quantity: float
    unit: str
    purpose: Optional[str] = None
    status: RequestStatus
    block_reason: Optional[str] = None
    alternative_suggestion: Optional[str] = None
    supervisor_review_comment: Optional[str] = None
    auto_review_result: Optional[str] = None
    auto_review_details: Optional[AutoReviewResult] = None
    created_at: datetime
    supervisor_reviewed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UsageReviewRequest(BaseModel):
    approved: bool
    comment: Optional[str] = None


class EmergencyPlanBase(BaseModel):
    name: str
    code: str
    applicable_categories: List[str]
    applicable_hazard_levels: List[str]
    applicable_alarm_levels: List[str]
    min_personnel_density: Optional[float] = None
    max_personnel_density: Optional[float] = None
    steps: List[Dict[str, Any]]
    required_equipment: List[str] = []
    evacuation_required: bool = False
    medical_assistance: bool = False
    fire_department: bool = False
    priority: int = 10


class EmergencyPlanCreate(EmergencyPlanBase):
    pass


class EmergencyPlanResponse(EmergencyPlanBase):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AlarmResponse(BaseModel):
    id: int
    alarm_no: str
    level: AlarmLevel
    type: str
    sensor_id: Optional[int] = None
    lab_id: Optional[int] = None
    cabinet_id: Optional[int] = None
    chemical_category: Optional[str] = None
    personnel_density: Optional[float] = None
    trigger_value: Optional[float] = None
    threshold_value: Optional[float] = None
    unit: Optional[str] = None
    description: str
    emergency_plan_id: Optional[int] = None
    emergency_plan: Optional[EmergencyPlanResponse] = None
    status: AlarmStatus
    location: Optional[str] = None
    resolution_notes: Optional[str] = None
    triggered_at: datetime
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    tasks: List["AlarmTaskResponse"] = []

    class Config:
        from_attributes = True


class AlarmTaskResponse(BaseModel):
    id: int
    alarm_id: int
    assignee_id: int
    assignee_name: Optional[str] = None
    task_description: str
    priority: int
    status: TaskStatus
    estimated_distance: Optional[float] = None
    notes: Optional[str] = None
    assigned_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


AlarmResponse.model_rebuild()


class AlarmTaskUpdate(BaseModel):
    status: Optional[TaskStatus] = None
    notes: Optional[str] = None


class AlarmUpdate(BaseModel):
    status: Optional[AlarmStatus] = None
    resolution_notes: Optional[str] = None


class WasteRecordCreate(BaseModel):
    chemical_id: int
    lab_id: Optional[int] = None
    waste_type: Optional[str] = None
    quantity: float
    unit: str
    container_no: Optional[str] = None
    container_type: Optional[str] = None


class WasteInspectionResult(BaseModel):
    seal_passed: bool
    seal_notes: Optional[str] = None
    label_passed: bool
    label_notes: Optional[str] = None
    violation_recorded: bool = False
    violation_type: Optional[str] = None
    violation_notes: Optional[str] = None


class WasteInspectionRequest(BaseModel):
    inspection_result: WasteInspectionResult


class WasteBatchCreate(BaseModel):
    disposal_center_id: int
    waste_record_ids: List[int]
    transport_company: Optional[str] = None
    driver_name: Optional[str] = None
    vehicle_plate: Optional[str] = None
    manifest_no: Optional[str] = None


class WasteRecordResponse(BaseModel):
    id: int
    waste_no: str
    chemical_id: int
    chemical_name: Optional[str] = None
    lab_id: Optional[int] = None
    waste_type: Optional[str] = None
    quantity: float
    unit: str
    container_no: Optional[str] = None
    container_type: Optional[str] = None
    seal_inspection_passed: bool
    seal_inspection_notes: Optional[str] = None
    label_inspection_passed: bool
    label_inspection_notes: Optional[str] = None
    violation_recorded: bool
    violation_type: Optional[str] = None
    violation_notes: Optional[str] = None
    status: WasteStatus
    batch_id: Optional[int] = None
    disposal_center_id: Optional[int] = None
    created_at: datetime
    inspected_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WasteBatchResponse(BaseModel):
    id: int
    batch_no: str
    disposal_center_id: int
    transport_company: Optional[str] = None
    driver_name: Optional[str] = None
    vehicle_plate: Optional[str] = None
    manifest_no: Optional[str] = None
    total_quantity: float
    status: str
    created_at: datetime
    shipped_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    waste_records: List[WasteRecordResponse] = []

    class Config:
        from_attributes = True


class DisposalCenterBase(BaseModel):
    name: str
    code: str
    address: str
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    license_no: Optional[str] = None
    allowed_waste_types: List[str] = []


class DisposalCenterResponse(DisposalCenterBase):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ReplenishmentResponse(BaseModel):
    id: int
    request_no: str
    chemical_id: int
    chemical_name: Optional[str] = None
    current_quantity: float
    safety_level: float
    requested_quantity: float
    unit: str
    reason: Optional[str] = None
    status: ReplenishmentStatus
    created_by_id: int
    lab_manager_id: Optional[int] = None
    safety_officer_id: Optional[int] = None
    lab_manager_comment: Optional[str] = None
    safety_officer_comment: Optional[str] = None
    reminder_sent_count: int
    purchase_order_no: Optional[str] = None
    created_at: datetime
    lab_manager_approved_at: Optional[datetime] = None
    safety_officer_approved_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ReplenishmentReview(BaseModel):
    approved: bool
    comment: Optional[str] = None


class DailyReportResponse(BaseModel):
    id: int
    report_date: date
    lab_id: Optional[int] = None
    lab_name: Optional[str] = None
    total_chemical_types: int
    total_inventory_quantity: float
    consumption_by_category: Optional[Dict[str, Any]] = None
    storage_status_summary: Optional[Dict[str, Any]] = None
    alarm_count_by_level: Optional[Dict[str, Any]] = None
    alarm_count_total: int
    usage_request_count: int
    inbound_count: int
    waste_count: int
    replenishment_count: int
    safety_incidents: Optional[List[Dict[str, Any]]] = None
    generated_at: datetime

    class Config:
        from_attributes = True


# ============ 监管总览看板 ============

class DashboardLinks(BaseModel):
    usage_supervisor_pending: str
    replenish_lab_manager_pending: str
    replenish_safety_pending: str
    waste_pending_inspection: str
    active_alarms: str
    low_stock: str
    today_inbound: str
    today_usage: str
    today_waste: str


class DashboardPendingApprovals(BaseModel):
    usage_supervisor: int
    replenish_lab_manager: int
    replenish_safety: int
    waste_inspection: int
    total: int


class DashboardActiveAlarms(BaseModel):
    triggered: int
    handling: int
    tasks_assigned: int
    total: int


class DashboardInventory(BaseModel):
    low_stock_items: int


class DashboardWasteSummary(BaseModel):
    pending_inspection: int
    batched: int
    in_transit: int
    submitted_today: int


class DashboardTodayStats(BaseModel):
    date: str
    inbound_approved: int
    inbound_total: int
    usage_approved: int
    usage_total: int
    waste_submitted: int


class DashboardLabSummary(BaseModel):
    lab_id: int
    lab_code: str
    lab_name: str
    pending_usage_supervisor: int
    pending_replenish_lab_manager: int
    pending_replenish_safety: int
    pending_waste_inspection: int
    active_alarms: int
    low_stock_items: int
    links: DashboardLinks


class DashboardOverviewResponse(BaseModel):
    generated_at: str
    scope_lab_ids: List[int]
    viewer_role: str
    viewer_id: int
    viewer_name: str
    pending_approvals: DashboardPendingApprovals
    active_alarms: DashboardActiveAlarms
    inventory: DashboardInventory
    waste: DashboardWasteSummary
    today: DashboardTodayStats
    lab_breakdown: List[DashboardLabSummary]


class NotificationResponse(BaseModel):
    id: int
    type: NotificationType
    title: str
    content: Optional[str] = None
    user_id: Optional[int] = None
    lab_id: Optional[int] = None
    related_id: Optional[int] = None
    related_type: Optional[str] = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class EventBusinessType(str):
    pass


class EventLogResponse(BaseModel):
    id: int
    event_no: str
    business_type: str
    event_type: str
    business_id: int
    business_no: Optional[str] = None
    lab_id: Optional[int] = None
    operator_id: Optional[int] = None
    target_role: Optional[str] = None
    target_user_id: Optional[int] = None
    title: str
    summary: Optional[str] = None
    handle_status: str
    detail_url: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AuditTrailResponse(BaseModel):
    id: int
    business_type: str
    business_id: int
    business_no: Optional[str] = None
    action: str
    stage_name: Optional[str] = None
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    operator_id: Optional[int] = None
    operator_name: Optional[str] = None
    operator_role: Optional[str] = None
    comment: Optional[str] = None
    duration_seconds: Optional[float] = None
    extra_data: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AlarmTaskProgressCreate(BaseModel):
    progress_status: str
    progress_percent: int = 0
    description: Optional[str] = None
    evidence_url: Optional[str] = None


class AlarmTaskProgressResponse(BaseModel):
    id: int
    task_id: int
    operator_id: Optional[int] = None
    operator_name: Optional[str] = None
    progress_status: str
    progress_percent: int
    description: Optional[str] = None
    evidence_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AlarmClosureCreate(BaseModel):
    root_cause: str
    handling_summary: str
    lessons_learned: Optional[str] = None
    improvement_actions: Optional[List[str]] = None
    effectiveness_rating: Optional[int] = None


class AlarmClosureResponse(BaseModel):
    id: int
    alarm_id: int
    closed_by_id: Optional[int] = None
    closed_by_name: Optional[str] = None
    root_cause: str
    handling_summary: str
    lessons_learned: Optional[str] = None
    improvement_actions: Optional[List[Any]] = None
    effectiveness_rating: Optional[int] = None
    verified_by_id: Optional[int] = None
    verified_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UsageRequestDetailResponse(UsageRequestResponse):
    audit_trails: List[AuditTrailResponse] = []


class ReplenishmentDetailResponse(ReplenishmentResponse):
    audit_trails: List[AuditTrailResponse] = []


class WasteRecordDetailResponse(WasteRecordResponse):
    audit_trails: List[AuditTrailResponse] = []


class AlarmDetailResponse(AlarmResponse):
    closure: Optional[AlarmClosureResponse] = None
    audit_trails: List[AuditTrailResponse] = []


class AlarmTaskDetailResponse(AlarmTaskResponse):
    progress_updates: List[AlarmTaskProgressResponse] = []
