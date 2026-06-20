from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.database import get_db
from app.models import (
    Batch, BatchStatus, Alert, QualityReport, SensorReading,
    Fermenter, Recipe
)
from app.schemas import (
    FermentationProgressResponse, QualityReportResponse
)
from app.utils import (
    get_current_stage, get_total_curve_days, parse_quality_report,
    generate_quality_report
)

router = APIRouter(prefix="/api/progress", tags=["发酵进度与质控报告"])


@router.get("/batch/{batch_id}", response_model=FermentationProgressResponse)
def get_batch_progress(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    current_time = datetime.now()
    stage_result = get_current_stage(batch, current_time)

    current_stage_name = None
    stage_elapsed_days = 0.0
    temperature_deviation = None

    if stage_result:
        stage, stage_elapsed, total_elapsed = stage_result
        current_stage_name = stage.name
        stage_elapsed_days = round(stage_elapsed, 2)

        recent_reading = (
            db.query(SensorReading)
            .filter(SensorReading.batch_id == batch_id)
            .order_by(SensorReading.timestamp.desc())
            .first()
        )
        if recent_reading:
            temperature_deviation = round(recent_reading.temperature - stage.target_temperature, 2)

    total_curve_days = get_total_curve_days(batch.recipe)

    if batch.status == BatchStatus.FERMENTING and batch.start_date:
        elapsed = (current_time - batch.start_date).total_seconds() / 86400.0
        remaining_days = max(0.0, round(total_curve_days - elapsed, 2))
    elif batch.end_date and batch.start_date:
        remaining_days = 0.0
    else:
        remaining_days = round(total_curve_days, 2)

    latest_reading = (
        db.query(SensorReading)
        .filter(SensorReading.batch_id == batch_id)
        .order_by(SensorReading.timestamp.desc())
        .first()
    )
    current_sg = latest_reading.specific_gravity if latest_reading else None

    if current_sg is not None and batch.recipe:
        sg_to_fg_distance = round(current_sg - batch.recipe.target_fg, 4)
    else:
        sg_to_fg_distance = None

    alert_count = db.query(Alert).filter(Alert.batch_id == batch_id).count()

    return FermentationProgressResponse(
        batch_id=batch.id,
        batch_number=batch.batch_number,
        current_stage=current_stage_name,
        stage_elapsed_days=stage_elapsed_days,
        temperature_deviation=temperature_deviation,
        current_sg=current_sg,
        sg_to_fg_distance=sg_to_fg_distance,
        remaining_days_estimate=remaining_days,
        alert_count=alert_count,
    )


@router.get("/reports", response_model=List[QualityReportResponse])
def list_quality_reports(
    recipe_id: Optional[int] = None,
    min_grade: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(QualityReport)

    if recipe_id:
        query = query.join(Batch).filter(Batch.recipe_id == recipe_id)

    reports = query.order_by(QualityReport.generated_at.desc()).all()

    result = []
    for report in reports:
        batch = report.batch
        if min_grade:
            grade_order = {"A": 0, "B": 1, "C": 2, "D": 3}
            if grade_order.get(report.quality_grade.value, 99) > grade_order.get(min_grade, -1):
                continue
        parsed = parse_quality_report(report, batch)
        result.append(QualityReportResponse(**parsed))

    return result


@router.get("/reports/batch/{batch_id}", response_model=QualityReportResponse)
def get_quality_report(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    report = db.query(QualityReport).filter(QualityReport.batch_id == batch_id).first()

    if not report:
        if batch.status != BatchStatus.COMPLETED:
            raise HTTPException(
                status_code=400,
                detail=f"批次当前状态为 {batch.status.value}，只有已完成的批次才有质控报告"
            )
        report = generate_quality_report(db, batch)
        db.commit()
        db.refresh(report)

    parsed = parse_quality_report(report, batch)
    return QualityReportResponse(**parsed)


@router.post("/reports/batch/{batch_id}/regenerate", response_model=QualityReportResponse)
def regenerate_quality_report(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    if batch.status != BatchStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"批次当前状态为 {batch.status.value}，只有已完成的批次才能生成质控报告"
        )

    existing = db.query(QualityReport).filter(QualityReport.batch_id == batch_id).first()
    if existing:
        db.delete(existing)
        db.flush()

    report = generate_quality_report(db, batch)
    db.commit()
    db.refresh(report)

    parsed = parse_quality_report(report, batch)
    return QualityReportResponse(**parsed)
