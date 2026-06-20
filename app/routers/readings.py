from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.database import get_db
from app.models import (
    Batch, BatchStatus, SensorReading
)
from app.schemas import (
    SensorReadingCreate, SensorReadingResponse
)
from app.utils import (
    get_current_stage,
    check_temperature_deviation,
    check_fermentation_stall,
    create_temperature_alert,
    create_stall_alert,
)

router = APIRouter(prefix="/api/readings", tags=["数据采集"])


@router.post("/batch/{batch_id}", response_model=SensorReadingResponse, status_code=status.HTTP_201_CREATED)
def report_reading(
    batch_id: int,
    data: SensorReadingCreate,
    db: Session = Depends(get_db)
):
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    if batch.status != BatchStatus.FERMENTING:
        raise HTTPException(
            status_code=400,
            detail=f"批次当前状态为 {batch.status.value}，只有发酵中的批次可以上报读数"
        )

    timestamp = data.timestamp or datetime.now()

    stage_result = get_current_stage(batch, timestamp)
    stage_name = None
    is_abnormal = 0

    reading = SensorReading(
        batch_id=batch_id,
        timestamp=timestamp,
        temperature=data.temperature,
        specific_gravity=data.specific_gravity,
        is_abnormal=0,
    )
    db.add(reading)
    db.flush()

    if stage_result:
        stage, stage_elapsed, total_elapsed = stage_result
        stage_name = stage.name
        reading.stage_name = stage_name

        is_temp_violation, severity, deviation = check_temperature_deviation(
            data.temperature, stage
        )
        if is_temp_violation:
            is_abnormal = 1
            create_temperature_alert(db, batch, reading, stage, deviation, severity)

    db.flush()

    is_stall, stall_severity, stall_count = check_fermentation_stall(db, batch_id, reading)
    if is_stall:
        is_abnormal = 1
        create_stall_alert(db, batch, reading, stall_count, stall_severity)

    reading.is_abnormal = is_abnormal

    db.commit()
    db.refresh(reading)
    return reading


@router.get("/batch/{batch_id}", response_model=List[SensorReadingResponse])
def list_batch_readings(
    batch_id: int,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    abnormal_only: bool = False,
    db: Session = Depends(get_db)
):
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    query = db.query(SensorReading).filter(SensorReading.batch_id == batch_id)
    if start_time:
        query = query.filter(SensorReading.timestamp >= start_time)
    if end_time:
        query = query.filter(SensorReading.timestamp <= end_time)
    if abnormal_only:
        query = query.filter(SensorReading.is_abnormal == 1)

    return query.order_by(SensorReading.timestamp.asc()).all()
