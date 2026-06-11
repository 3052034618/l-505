from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import timedelta
from typing import List
from database import get_db
from auth import create_access_token, verify_password, get_password_hash, get_current_user, require_roles
from config import settings
import models
import schemas

router = APIRouter(prefix="/api/auth", tags=["认证管理"])


@router.post("/login", response_model=schemas.Token)
def login(request: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == request.username).first()
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="账号已被禁用"
        )
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role.value}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=schemas.UserResponse)
def get_current_user_info(current_user: models.User = Depends(get_current_user)):
    return current_user


router_users = APIRouter(prefix="/api/users", tags=["用户管理"])


@router_users.post("", response_model=schemas.UserResponse, dependencies=[Depends(require_roles(models.UserRole.ADMIN))])
def create_user(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.username == user_in.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = models.User(
        **user_in.model_dump(exclude={"password"}),
        password_hash=get_password_hash(user_in.password)
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router_users.get("", response_model=List[schemas.UserResponse], dependencies=[Depends(require_roles(models.UserRole.ADMIN, models.UserRole.LAB_MANAGER, models.UserRole.SAFETY_OFFICER))])
def list_users(role: str = None, lab_id: int = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    query = db.query(models.User)
    if current_user.role not in [models.UserRole.ADMIN]:
        query = query.filter(models.User.lab_id == current_user.lab_id)
    if role:
        query = query.filter(models.User.role == role)
    if lab_id:
        query = query.filter(models.User.lab_id == lab_id)
    return query.offset(skip).limit(limit).all()


@router_users.get("/{user_id}", response_model=schemas.UserResponse)
def get_user(user_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if current_user.role not in [models.UserRole.ADMIN] and user.id != current_user.id and user.lab_id != current_user.lab_id:
        raise HTTPException(status_code=403, detail="无权限查看该用户")
    return user


@router_users.put("/{user_id}", response_model=schemas.UserResponse)
def update_user(user_id: int, user_in: schemas.UserUpdate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if current_user.role not in [models.UserRole.ADMIN] and user.id != current_user.id:
        raise HTTPException(status_code=403, detail="无权限修改该用户")
    update_data = user_in.model_dump(exclude_unset=True)
    if "password" in update_data and update_data["password"]:
        update_data["password_hash"] = get_password_hash(update_data.pop("password"))
    for field, value in update_data.items():
        if value is not None:
            setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user
