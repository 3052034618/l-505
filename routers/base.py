from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from database import get_db
from auth import get_current_user, require_roles
import models
import schemas

router_labs = APIRouter(prefix="/api/laboratories", tags=["实验室管理"])


@router_labs.post("", response_model=schemas.LaboratoryResponse, dependencies=[Depends(require_roles(models.UserRole.ADMIN))])
def create_laboratory(lab_in: schemas.LaboratoryCreate, db: Session = Depends(get_db)):
    if db.query(models.Laboratory).filter(models.Laboratory.code == lab_in.code).first():
        raise HTTPException(status_code=400, detail="实验室编码已存在")
    if db.query(models.Laboratory).filter(models.Laboratory.name == lab_in.name).first():
        raise HTTPException(status_code=400, detail="实验室名称已存在")
    lab = models.Laboratory(**lab_in.model_dump())
    db.add(lab)
    db.commit()
    db.refresh(lab)
    return lab


@router_labs.get("", response_model=List[schemas.LaboratoryResponse])
def list_laboratories(skip: int = 0, limit: int = 100, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    query = db.query(models.Laboratory).filter(models.Laboratory.is_active == True)
    return query.offset(skip).limit(limit).all()


@router_labs.get("/{lab_id}", response_model=schemas.LaboratoryResponse)
def get_laboratory(lab_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    lab = db.query(models.Laboratory).filter(models.Laboratory.id == lab_id).first()
    if not lab:
        raise HTTPException(status_code=404, detail="实验室不存在")
    return lab


router_chemicals = APIRouter(prefix="/api/chemicals", tags=["化学品管理"])


@router_chemicals.post("", response_model=schemas.ChemicalResponse, dependencies=[Depends(require_roles(models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER))])
def create_chemical(chemical_in: schemas.ChemicalCreate, db: Session = Depends(get_db)):
    chemical = models.Chemical(**chemical_in.model_dump())
    db.add(chemical)
    db.commit()
    db.refresh(chemical)
    return chemical


@router_chemicals.get("", response_model=List[schemas.ChemicalResponse])
def list_chemicals(
    category: Optional[str] = None,
    hazard_level: Optional[str] = None,
    lab_id: Optional[int] = None,
    keyword: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.Chemical).filter(models.Chemical.is_active == True)
    if category:
        query = query.filter(models.Chemical.category == category)
    if hazard_level:
        query = query.filter(models.Chemical.hazard_level == hazard_level)
    if lab_id:
        query = query.filter(models.Chemical.lab_id == lab_id)
    if keyword:
        query = query.filter(
            (models.Chemical.name.contains(keyword)) |
            (models.Chemical.cas_no.contains(keyword))
        )
    return query.offset(skip).limit(limit).all()


@router_chemicals.get("/{chemical_id}", response_model=schemas.ChemicalResponse)
def get_chemical(chemical_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    chemical = db.query(models.Chemical).filter(models.Chemical.id == chemical_id).first()
    if not chemical:
        raise HTTPException(status_code=404, detail="化学品不存在")
    return chemical


@router_chemicals.put("/{chemical_id}", response_model=schemas.ChemicalResponse, dependencies=[Depends(require_roles(models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER))])
def update_chemical(chemical_id: int, chemical_in: schemas.ChemicalUpdate, db: Session = Depends(get_db)):
    chemical = db.query(models.Chemical).filter(models.Chemical.id == chemical_id).first()
    if not chemical:
        raise HTTPException(status_code=404, detail="化学品不存在")
    update_data = chemical_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            setattr(chemical, field, value)
    db.commit()
    db.refresh(chemical)
    return chemical


router_cabinets = APIRouter(prefix="/api/cabinets", tags=["存储柜管理"])


@router_cabinets.post("", response_model=schemas.StorageCabinetResponse, dependencies=[Depends(require_roles(models.UserRole.ADMIN, models.UserRole.SAFETY_OFFICER, models.UserRole.LAB_MANAGER))])
def create_cabinet(cabinet_in: schemas.StorageCabinetCreate, db: Session = Depends(get_db)):
    if db.query(models.StorageCabinet).filter(models.StorageCabinet.cabinet_no == cabinet_in.cabinet_no).first():
        raise HTTPException(status_code=400, detail="存储柜编号已存在")
    cabinet = models.StorageCabinet(**cabinet_in.model_dump())
    db.add(cabinet)
    db.commit()
    db.refresh(cabinet)
    return cabinet


@router_cabinets.get("", response_model=List[schemas.StorageCabinetResponse])
def list_cabinets(
    lab_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.StorageCabinet).filter(models.StorageCabinet.is_active == True)
    if lab_id:
        query = query.filter(models.StorageCabinet.lab_id == lab_id)
    return query.offset(skip).limit(limit).all()


@router_cabinets.get("/{cabinet_id}", response_model=schemas.StorageCabinetResponse)
def get_cabinet(cabinet_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    cabinet = db.query(models.StorageCabinet).filter(models.StorageCabinet.id == cabinet_id).first()
    if not cabinet:
        raise HTTPException(status_code=404, detail="存储柜不存在")
    return cabinet


router_inventory = APIRouter(prefix="/api/inventory", tags=["库存管理"])


@router_inventory.get("", response_model=List[schemas.InventoryResponse])
def list_inventory(
    lab_id: Optional[int] = None,
    cabinet_id: Optional[int] = None,
    chemical_id: Optional[int] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.Inventory)
    if lab_id:
        query = query.join(models.StorageCabinet).filter(models.StorageCabinet.lab_id == lab_id)
    if cabinet_id:
        query = query.filter(models.Inventory.cabinet_id == cabinet_id)
    if chemical_id:
        query = query.filter(models.Inventory.chemical_id == chemical_id)
    if status:
        query = query.filter(models.Inventory.status == status)
    return query.offset(skip).limit(limit).all()


@router_inventory.get("/{inventory_id}", response_model=schemas.InventoryResponse)
def get_inventory(inventory_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    inventory = db.query(models.Inventory).filter(models.Inventory.id == inventory_id).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="库存记录不存在")
    return inventory


@router_inventory.get("/low-stock/alert")
def get_low_stock_alerts(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    low_stock = db.query(models.Inventory).filter(
        models.Inventory.current_quantity <= models.Inventory.safety_level
    ).all()
    return {
        "count": len(low_stock),
        "items": [
            {
                "id": inv.id,
                "chemical_name": inv.chemical.name if inv.chemical else None,
                "cas_no": inv.chemical.cas_no if inv.chemical else None,
                "category": inv.chemical.category.value if inv.chemical else None,
                "current_quantity": inv.current_quantity,
                "safety_level": inv.safety_level,
                "unit": inv.unit,
                "cabinet_no": inv.cabinet.cabinet_no if inv.cabinet else None,
                "batch_no": inv.batch_no
            }
            for inv in low_stock
        ]
    }
