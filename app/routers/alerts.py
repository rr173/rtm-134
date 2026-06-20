from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.database import get_db
from app.models import (
    Alert, AlertType, AlertSeverity, AlertStatus,
    Batch, Fermenter
)
from app.schemas import AlertResponse, AlertUpdate

router = APIRouter(prefix="/api/alerts", tags=["告警系统"])


@router.get("", response_model=List[AlertResponse])
def list_alerts(
    batch_id: Optional[int] = None,
    fermenter_id: Optional[int] = None,
    alert_type: Optional[AlertType] = None,
    severity: Optional[AlertSeverity] = None,
    status: Optional[AlertStatus] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Alert)

    if fermenter_id:
        fermenter = db.query(Fermenter).filter(Fermenter.id == fermenter_id).first()
        if not fermenter:
            raise HTTPException(status_code=404, detail="发酵罐不存在")
        batch_ids = [b.id for b in fermenter.batches]
        if batch_ids:
            query = query.filter(Alert.batch_id.in_(batch_ids))
        else:
            return []
    elif batch_id:
        batch = db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise HTTPException(status_code=404, detail="批次不存在")
        query = query.filter(Alert.batch_id == batch_id)

    if alert_type:
        query = query.filter(Alert.alert_type == alert_type)
    if severity:
        query = query.filter(Alert.severity == severity)
    if status:
        query = query.filter(Alert.status == status)

    return query.order_by(Alert.triggered_at.desc()).all()


@router.get("/{alert_id}", response_model=AlertResponse)
def get_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="告警不存在")
    return alert


@router.put("/{alert_id}/acknowledge", response_model=AlertResponse)
def acknowledge_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="告警不存在")

    if alert.status == AlertStatus.CLOSED:
        raise HTTPException(status_code=400, detail="告警已关闭，无法确认")

    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_at = datetime.now()
    db.commit()
    db.refresh(alert)
    return alert


@router.put("/{alert_id}/close", response_model=AlertResponse)
def close_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="告警不存在")

    if alert.status == AlertStatus.OPEN:
        alert.acknowledged_at = datetime.now()

    alert.status = AlertStatus.CLOSED
    alert.closed_at = datetime.now()
    db.commit()
    db.refresh(alert)
    return alert


@router.put("/{alert_id}", response_model=AlertResponse)
def update_alert(alert_id: int, data: AlertUpdate, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="告警不存在")

    update_data = data.model_dump(exclude_unset=True)
    if "status" in update_data:
        new_status = update_data["status"]
        if new_status == AlertStatus.ACKNOWLEDGED and alert.acknowledged_at is None:
            alert.acknowledged_at = datetime.now()
        if new_status == AlertStatus.CLOSED:
            if alert.acknowledged_at is None:
                alert.acknowledged_at = datetime.now()
            alert.closed_at = datetime.now()
        alert.status = new_status

    db.commit()
    db.refresh(alert)
    return alert
