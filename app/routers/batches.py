from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.database import get_db
from app.models import (
    Batch, Fermenter, Recipe, BatchStatus, FermenterStatus,
    QualityReport
)
from app.schemas import (
    BatchStartRequest, BatchEndRequest, BatchResponse
)
from app.utils import (
    generate_batch_number, calculate_actual_attenuation,
    generate_quality_report
)

router = APIRouter(prefix="/api/batches", tags=["批次管理"])


@router.get("", response_model=List[BatchResponse])
def list_batches(
    status: Optional[BatchStatus] = None,
    fermenter_id: Optional[int] = None,
    recipe_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Batch)
    if status:
        query = query.filter(Batch.status == status)
    if fermenter_id:
        query = query.filter(Batch.fermenter_id == fermenter_id)
    if recipe_id:
        query = query.filter(Batch.recipe_id == recipe_id)
    return query.order_by(Batch.start_date.desc()).all()


@router.get("/{batch_id}", response_model=BatchResponse)
def get_batch(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    return batch


@router.post("/start", response_model=BatchResponse, status_code=status.HTTP_201_CREATED)
def start_batch(data: BatchStartRequest, db: Session = Depends(get_db)):
    fermenter = db.query(Fermenter).filter(Fermenter.id == data.fermenter_id).first()
    if not fermenter:
        raise HTTPException(status_code=404, detail="发酵罐不存在")

    if fermenter.status != FermenterStatus.IDLE:
        raise HTTPException(
            status_code=400,
            detail=f"发酵罐 {fermenter.code} 当前状态为 {fermenter.status.value}，必须为空闲状态才能开始批次"
        )

    active_batch = (
        db.query(Batch)
        .filter(
            Batch.fermenter_id == data.fermenter_id,
            Batch.status == BatchStatus.FERMENTING
        )
        .first()
    )
    if active_batch:
        raise HTTPException(
            status_code=400,
            detail=f"发酵罐 {fermenter.code} 已有进行中的批次 {active_batch.batch_number}"
        )

    recipe = db.query(Recipe).filter(Recipe.id == data.recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")

    start_date = data.start_date or datetime.now()
    batch_number = generate_batch_number(db, start_date)

    batch = Batch(
        batch_number=batch_number,
        fermenter_id=data.fermenter_id,
        recipe_id=data.recipe_id,
        start_date=start_date,
        measured_og=data.measured_og,
        status=BatchStatus.FERMENTING,
    )
    db.add(batch)

    fermenter.status = FermenterStatus.FERMENTING

    db.commit()
    db.refresh(batch)
    return batch


@router.post("/{batch_id}/end", response_model=BatchResponse)
def end_batch(batch_id: int, data: BatchEndRequest, db: Session = Depends(get_db)):
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    if batch.status != BatchStatus.FERMENTING:
        raise HTTPException(
            status_code=400,
            detail=f"批次当前状态为 {batch.status.value}，只有发酵中的批次可以结束"
        )

    end_date = data.end_date or datetime.now()
    if end_date < batch.start_date:
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")

    actual_attenuation = calculate_actual_attenuation(batch.measured_og, data.measured_fg)

    batch.end_date = end_date
    batch.measured_fg = data.measured_fg
    batch.actual_attenuation = actual_attenuation
    batch.status = BatchStatus.COMPLETED

    fermenter = db.query(Fermenter).filter(Fermenter.id == batch.fermenter_id).first()
    if fermenter:
        fermenter.status = FermenterStatus.IDLE

    existing_report = db.query(QualityReport).filter(QualityReport.batch_id == batch_id).first()
    if existing_report:
        db.delete(existing_report)

    generate_quality_report(db, batch)

    db.commit()
    db.refresh(batch)
    return batch


@router.post("/{batch_id}/abort", response_model=BatchResponse)
def abort_batch(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    if batch.status != BatchStatus.FERMENTING:
        raise HTTPException(
            status_code=400,
            detail=f"批次当前状态为 {batch.status.value}，只有发酵中的批次可以终止"
        )

    batch.end_date = datetime.now()
    batch.status = BatchStatus.ABORTED

    fermenter = db.query(Fermenter).filter(Fermenter.id == batch.fermenter_id).first()
    if fermenter:
        fermenter.status = FermenterStatus.IDLE

    db.commit()
    db.refresh(batch)
    return batch
