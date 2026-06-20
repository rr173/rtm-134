from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models import Fermenter, FermenterStatus, Batch, BatchStatus
from app.schemas import FermenterCreate, FermenterUpdate, FermenterResponse

router = APIRouter(prefix="/api/fermenters", tags=["发酵罐管理"])


@router.get("", response_model=List[FermenterResponse])
def list_fermenters(
    status: FermenterStatus = None,
    db: Session = Depends(get_db)
):
    query = db.query(Fermenter)
    if status:
        query = query.filter(Fermenter.status == status)
    return query.order_by(Fermenter.code).all()


@router.get("/{fermenter_id}", response_model=FermenterResponse)
def get_fermenter(fermenter_id: int, db: Session = Depends(get_db)):
    fermenter = db.query(Fermenter).filter(Fermenter.id == fermenter_id).first()
    if not fermenter:
        raise HTTPException(status_code=404, detail="发酵罐不存在")
    return fermenter


@router.post("", response_model=FermenterResponse, status_code=status.HTTP_201_CREATED)
def create_fermenter(data: FermenterCreate, db: Session = Depends(get_db)):
    existing = db.query(Fermenter).filter(Fermenter.code == data.code).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"编号 {data.code} 已存在")
    fermenter = Fermenter(**data.model_dump())
    db.add(fermenter)
    db.commit()
    db.refresh(fermenter)
    return fermenter


@router.put("/{fermenter_id}", response_model=FermenterResponse)
def update_fermenter(
    fermenter_id: int,
    data: FermenterUpdate,
    db: Session = Depends(get_db)
):
    fermenter = db.query(Fermenter).filter(Fermenter.id == fermenter_id).first()
    if not fermenter:
        raise HTTPException(status_code=404, detail="发酵罐不存在")

    update_data = data.model_dump(exclude_unset=True)
    if "code" in update_data and update_data["code"] != fermenter.code:
        existing = db.query(Fermenter).filter(Fermenter.code == update_data["code"]).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"编号 {update_data['code']} 已存在")

    for key, value in update_data.items():
        setattr(fermenter, key, value)
    db.commit()
    db.refresh(fermenter)
    return fermenter


@router.delete("/{fermenter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fermenter(fermenter_id: int, db: Session = Depends(get_db)):
    fermenter = db.query(Fermenter).filter(Fermenter.id == fermenter_id).first()
    if not fermenter:
        raise HTTPException(status_code=404, detail="发酵罐不存在")

    active_batch = (
        db.query(Batch)
        .filter(
            Batch.fermenter_id == fermenter_id,
            Batch.status == BatchStatus.FERMENTING
        )
        .first()
    )
    if active_batch:
        raise HTTPException(
            status_code=400,
            detail=f"发酵罐 {fermenter.code} 正在进行批次 {active_batch.batch_number}，无法删除"
        )

    if fermenter.status == FermenterStatus.FERMENTING:
        raise HTTPException(
            status_code=400,
            detail=f"发酵罐处于发酵中状态，无法删除"
        )

    db.delete(fermenter)
    db.commit()
    return None
