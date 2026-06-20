from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta

from app.database import get_db
from app.models import (
    Fermenter, Batch, BatchStatus, Recipe, Alert,
    AlertType, AlertSeverity, QualityReport, QualityGrade
)
from app.schemas import (
    FermenterUtilization, RecipeStat, AlertFrequencyByRecipe
)

router = APIRouter(prefix="/api/stats", tags=["统计分析"])


def _days_overlap(
    start1: datetime, end1: Optional[datetime],
    start2: datetime, end2: datetime
) -> float:
    s = max(start1, start2)
    e = min(end1 or datetime.now(), end2)
    if s >= e:
        return 0.0
    return (e - s).total_seconds() / 86400.0


@router.get("/fermenter-utilization", response_model=List[FermenterUtilization])
def get_fermenter_utilization(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    fermenter_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    if end_date is None:
        end_date = datetime.now()
    if start_date is None:
        start_date = end_date - timedelta(days=30)

    if start_date >= end_date:
        raise HTTPException(status_code=400, detail="开始日期必须早于结束日期")

    total_days = (end_date - start_date).total_seconds() / 86400.0

    query = db.query(Fermenter)
    if fermenter_id:
        query = query.filter(Fermenter.id == fermenter_id)
    fermenters = query.order_by(Fermenter.code).all()

    result = []
    for f in fermenters:
        batches = (
            db.query(Batch)
            .filter(
                Batch.fermenter_id == f.id,
                Batch.start_date < end_date,
            )
            .all()
        )

        fermenting_days = 0.0
        for b in batches:
            overlap = _days_overlap(b.start_date, b.end_date, start_date, end_date)
            fermenting_days += overlap

        fermenting_days_int = int(round(fermenting_days))
        total_days_int = int(round(total_days))
        utilization = round(fermenting_days / total_days * 100, 2) if total_days > 0 else 0.0

        result.append(FermenterUtilization(
            fermenter_id=f.id,
            fermenter_code=f.code,
            total_days=total_days_int,
            fermenting_days=fermenting_days_int,
            utilization_rate=utilization,
        ))

    return result


@router.get("/recipe-stats", response_model=List[RecipeStat])
def get_recipe_stats(db: Session = Depends(get_db)):
    recipes = db.query(Recipe).order_by(Recipe.name).all()

    grade_scores = {QualityGrade.A: 4.0, QualityGrade.B: 3.0, QualityGrade.C: 2.0, QualityGrade.D: 1.0}

    result = []
    for r in recipes:
        completed_batches = [
            b for b in r.batches if b.status == BatchStatus.COMPLETED
        ]

        attenuations = [b.actual_attenuation for b in completed_batches if b.actual_attenuation is not None]
        avg_attenuation = round(sum(attenuations) / len(attenuations), 2) if attenuations else None

        reports = db.query(QualityReport).join(Batch).filter(Batch.recipe_id == r.id).all()
        scores = [grade_scores.get(rep.quality_grade, 0.0) for rep in reports]
        avg_grade = round(sum(scores) / len(scores), 2) if scores else None

        result.append(RecipeStat(
            recipe_id=r.id,
            recipe_name=r.name,
            style=r.style,
            batch_count=len(r.batches),
            avg_attenuation=avg_attenuation,
            avg_grade_score=avg_grade,
        ))

    return result


@router.get("/alert-frequency-by-recipe", response_model=List[AlertFrequencyByRecipe])
def get_alert_frequency_by_recipe(db: Session = Depends(get_db)):
    recipes = db.query(Recipe).order_by(Recipe.name).all()

    result = []
    for r in recipes:
        batch_ids = [b.id for b in r.batches]

        total_alerts = 0
        temp_alerts = 0
        stall_alerts = 0
        critical_alerts = 0

        if batch_ids:
            alerts = db.query(Alert).filter(Alert.batch_id.in_(batch_ids)).all()
            total_alerts = len(alerts)
            temp_alerts = len([a for a in alerts if a.alert_type == AlertType.TEMPERATURE_DEVIATION])
            stall_alerts = len([a for a in alerts if a.alert_type == AlertType.FERMENTATION_STALL])
            critical_alerts = len([a for a in alerts if a.severity == AlertSeverity.CRITICAL])

        batch_count = len(r.batches)
        alerts_per_batch = round(total_alerts / batch_count, 2) if batch_count > 0 else 0.0

        result.append(AlertFrequencyByRecipe(
            recipe_id=r.id,
            recipe_name=r.name,
            style=r.style,
            total_alerts=total_alerts,
            temperature_alerts=temp_alerts,
            stall_alerts=stall_alerts,
            critical_alerts=critical_alerts,
            batch_count=batch_count,
            alerts_per_batch=alerts_per_batch,
        ))

    result.sort(key=lambda x: x.alerts_per_batch, reverse=True)
    return result


@router.get("/summary")
def get_summary(db: Session = Depends(get_db)):
    total_fermenters = db.query(Fermenter).count()
    fermenting_fermenters = (
        db.query(Fermenter).filter(Fermenter.status == "发酵中").count()
    )
    idle_fermenters = (
        db.query(Fermenter).filter(Fermenter.status == "空闲").count()
    )

    total_batches = db.query(Batch).count()
    active_batches = (
        db.query(Batch).filter(Batch.status == BatchStatus.FERMENTING).count()
    )
    completed_batches = (
        db.query(Batch).filter(Batch.status == BatchStatus.COMPLETED).count()
    )

    total_alerts = db.query(Alert).count()
    open_alerts = db.query(Alert).filter(Alert.status == "open").count()
    critical_alerts = db.query(Alert).filter(Alert.severity == "critical").count()

    total_recipes = db.query(Recipe).count()
    total_reports = db.query(QualityReport).count()

    grade_counts = {}
    for grade in ["A", "B", "C", "D"]:
        grade_counts[grade] = (
            db.query(QualityReport).filter(QualityReport.quality_grade == grade).count()
        )

    return {
        "fermenters": {
            "total": total_fermenters,
            "fermenting": fermenting_fermenters,
            "idle": idle_fermenters,
        },
        "batches": {
            "total": total_batches,
            "active": active_batches,
            "completed": completed_batches,
        },
        "alerts": {
            "total": total_alerts,
            "open": open_alerts,
            "critical": critical_alerts,
        },
        "recipes": {
            "total": total_recipes,
        },
        "quality_reports": {
            "total": total_reports,
            "grade_distribution": grade_counts,
        },
    }
