from typing import List, Optional
from sqlalchemy.orm import Session
from datetime import datetime
import models
import schemas


class NotificationService:
    @staticmethod
    def create_notification(
        db: Session,
        notification_type: models.NotificationType,
        title: str,
        content: str = "",
        user_ids: Optional[List[int]] = None,
        lab_id: Optional[int] = None,
        roles: Optional[List[models.UserRole]] = None,
        related_id: Optional[int] = None,
        related_type: Optional[str] = None,
    ) -> List[models.Notification]:
        notifications = []
        target_users = set()

        if user_ids:
            for uid in user_ids:
                target_users.add(uid)

        if roles:
            users = db.query(models.User).filter(models.User.role.in_(roles), models.User.is_active == True).all()
            for u in users:
                target_users.add(u.id)

        if lab_id and not roles:
            users = db.query(models.User).filter(models.User.lab_id == lab_id, models.User.is_active == True).all()
            for u in users:
                target_users.add(u.id)

        if lab_id and roles:
            users = db.query(models.User).filter(
                models.User.lab_id == lab_id,
                models.User.role.in_(roles),
                models.User.is_active == True
            ).all()
            for u in users:
                target_users.add(u.id)

        for uid in target_users:
            notification = models.Notification(
                type=notification_type,
                title=title,
                content=content,
                user_id=uid,
                lab_id=lab_id,
                related_id=related_id,
                related_type=related_type,
                created_at=datetime.utcnow()
            )
            db.add(notification)
            notifications.append(notification)

        db.commit()
        for n in notifications:
            db.refresh(n)
        return notifications

    @staticmethod
    def get_user_notifications(db: Session, user_id: int, skip: int = 0, limit: int = 100, unread_only: bool = False):
        query = db.query(models.Notification).filter(models.Notification.user_id == user_id)
        if unread_only:
            query = query.filter(models.Notification.is_read == False)
        return query.order_by(models.Notification.created_at.desc()).offset(skip).limit(limit).all()

    @staticmethod
    def mark_as_read(db: Session, notification_id: int, user_id: int) -> bool:
        notification = db.query(models.Notification).filter(
            models.Notification.id == notification_id,
            models.Notification.user_id == user_id
        ).first()
        if notification:
            notification.is_read = True
            db.commit()
            return True
        return False

    @staticmethod
    def mark_all_as_read(db: Session, user_id: int) -> int:
        count = db.query(models.Notification).filter(
            models.Notification.user_id == user_id,
            models.Notification.is_read == False
        ).update({"is_read": True})
        db.commit()
        return count


notification_service = NotificationService()
