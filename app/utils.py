from datetime import datetime, timedelta
from typing import Optional, Tuple, List
from sqlalchemy.orm import Session
import json

from app.models import (
    Batch, Recipe, FermentationStage, SensorReading, Alert,
    AlertType, AlertSeverity, AlertStatus, QualityReport, QualityGrade,
    FermenterStatus
)
from app.schemas import StageTemperatureStat


def get_current_stage(batch: Batch, current_time: Optional[datetime] = None) -> Optional[Tuple[FermentationStage, float, float]]:
    if not batch.start_date:
        return None
    if current_time is None:
        current_time = datetime.now()

    elapsed = current_time - batch.start_date
    elapsed_days = elapsed.total_seconds() / 86400.0

    recipe = batch.recipe
    if not recipe or not recipe.stages:
        return None

    cumulative_days = 0.0
    for stage in recipe.stages:
        stage_start = cumulative_days
        stage_end = cumulative_days + stage.duration_days
        if elapsed_days < stage_end:
            stage_elapsed = elapsed_days - stage_start
            return (stage, stage_elapsed, elapsed_days)
        cumulative_days = stage_end

    last_stage = recipe.stages[-1]
    total_curve_days = cumulative_days
    stage_elapsed = elapsed_days - (total_curve_days - last_stage.duration_days)
    return (last_stage, stage_elapsed, elapsed_days)


def get_total_curve_days(recipe: Recipe) -> int:
    return sum(s.duration_days for s in recipe.stages)


def check_temperature_deviation(
    temperature: float,
    stage: FermentationStage
) -> Tuple[bool, AlertSeverity, float]:
    deviation = abs(temperature - stage.target_temperature)
    tolerance = stage.temperature_tolerance
    is_violation = deviation > tolerance
    if is_violation:
        if deviation > 2 * tolerance:
            severity = AlertSeverity.CRITICAL
        else:
            severity = AlertSeverity.WARNING
    else:
        severity = AlertSeverity.WARNING
    return (is_violation, severity, round(temperature - stage.target_temperature, 2))


def check_fermentation_stall(
    db: Session,
    batch_id: int,
    current_reading: SensorReading
) -> Tuple[bool, AlertSeverity, int]:
    recent_readings = (
        db.query(SensorReading)
        .filter(SensorReading.batch_id == batch_id)
        .order_by(SensorReading.timestamp.desc())
        .limit(6)
        .all()
    )

    if len(recent_readings) < 3:
        return (False, AlertSeverity.WARNING, 0)

    sgs = [r.specific_gravity for r in recent_readings]

    max_consecutive = 0
    current_consecutive = 0
    for i in range(len(sgs) - 1):
        change = abs(sgs[i] - sgs[i + 1])
        if change < 0.001:
            current_consecutive += 1
            if current_consecutive > max_consecutive:
                max_consecutive = current_consecutive
        else:
            current_consecutive = 0

    if max_consecutive >= 2:
        is_stall = True
    else:
        is_stall = False

    if max_consecutive >= 5:
        severity = AlertSeverity.CRITICAL
    else:
        severity = AlertSeverity.WARNING

    return (is_stall, severity, max_consecutive)


def create_temperature_alert(
    db: Session,
    batch: Batch,
    reading: SensorReading,
    stage: FermentationStage,
    deviation: float,
    severity: AlertSeverity
) -> Alert:
    alert = Alert(
        alert_type=AlertType.TEMPERATURE_DEVIATION,
        severity=severity,
        batch_id=batch.id,
        reading_id=reading.id,
        trigger_value=f"温度={reading.temperature}°C, 目标={stage.target_temperature}°C, 偏差={deviation:+.2f}°C, 允许±{stage.temperature_tolerance}°C",
        stage_info=f"阶段:{stage.name}",
        status=AlertStatus.OPEN,
        triggered_at=reading.timestamp,
        description=f"温度超出允许范围: 当前{reading.temperature}°C, 目标{stage.target_temperature}°C, 偏差{deviation:+.2f}°C"
    )
    db.add(alert)
    db.flush()
    return alert


def create_stall_alert(
    db: Session,
    batch: Batch,
    reading: SensorReading,
    stall_count: int,
    severity: AlertSeverity
) -> Alert:
    existing_recent = (
        db.query(Alert)
        .filter(
            Alert.batch_id == batch.id,
            Alert.alert_type == AlertType.FERMENTATION_STALL,
            Alert.triggered_at > (reading.timestamp - timedelta(hours=6))
        )
        .first()
    )
    if existing_recent:
        return existing_recent

    alert = Alert(
        alert_type=AlertType.FERMENTATION_STALL,
        severity=severity,
        batch_id=batch.id,
        reading_id=reading.id,
        trigger_value=f"比重连续{stall_count}次变化小于0.001, 当前SG={reading.specific_gravity}",
        stage_info="发酵停滞检测",
        status=AlertStatus.OPEN,
        triggered_at=reading.timestamp,
        description=f"检测到发酵停滞: 最近{stall_count}次连续读数比重变化<0.001, 当前SG={reading.specific_gravity}"
    )
    db.add(alert)
    db.flush()
    return alert


def calculate_actual_attenuation(og: float, fg: float) -> float:
    if og <= 1.0:
        return 0.0
    return round(((og - fg) / (og - 1.0)) * 100, 2)


def generate_batch_number(db: Session, start_date: Optional[datetime] = None) -> str:
    if start_date is None:
        start_date = datetime.now()
    date_str = start_date.strftime("%Y%m%d")
    prefix = f"B{date_str}-"

    last_batch = (
        db.query(Batch)
        .filter(Batch.batch_number.like(f"{prefix}%"))
        .order_by(Batch.batch_number.desc())
        .first()
    )

    if last_batch:
        try:
            seq_str = last_batch.batch_number.split("-")[-1]
            seq = int(seq_str) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1

    return f"{prefix}{seq:03d}"


def compute_quality_grade(
    total_readings: int,
    temp_violations: int,
    critical_alerts: int
) -> QualityGrade:
    violation_rate = (temp_violations / total_readings * 100) if total_readings > 0 else 0

    if critical_alerts == 0 and violation_rate < 5:
        return QualityGrade.A
    elif critical_alerts == 0 and 5 <= violation_rate < 15:
        return QualityGrade.B
    elif critical_alerts <= 2:
        return QualityGrade.C
    else:
        return QualityGrade.D


def generate_quality_report(db: Session, batch: Batch) -> QualityReport:
    from app.schemas import StageTemperatureStat

    readings = (
        db.query(SensorReading)
        .filter(SensorReading.batch_id == batch.id)
        .order_by(SensorReading.timestamp.asc())
        .all()
    )
    alerts = (
        db.query(Alert)
        .filter(Alert.batch_id == batch.id)
        .all()
    )

    stage_stats_map = {}
    total_readings = len(readings)
    temp_violations = 0

    for stage in batch.recipe.stages:
        stage_stats_map[stage.name] = {
            "temps": [],
            "max_deviation": 0.0,
            "violations": 0,
            "total": 0,
            "target_temp": stage.target_temperature,
            "tolerance": stage.temperature_tolerance,
        }

    reading_stages = {}
    for r in readings:
        result = get_current_stage(batch, r.timestamp)
        if result:
            stage, _, _ = result
            reading_stages[r.id] = stage.name

    for r in readings:
        stage_name = reading_stages.get(r.id)
        if stage_name and stage_name in stage_stats_map:
            stats = stage_stats_map[stage_name]
            stats["temps"].append(r.temperature)
            stats["total"] += 1
            deviation = abs(r.temperature - stats["target_temp"])
            if deviation > stats["max_deviation"]:
                stats["max_deviation"] = round(deviation, 2)
            if deviation > stats["tolerance"]:
                stats["violations"] += 1
                temp_violations += 1

    stage_stats: List[StageTemperatureStat] = []
    for stage in batch.recipe.stages:
        s = stage_stats_map[stage.name]
        avg_temp = round(sum(s["temps"]) / len(s["temps"]), 2) if s["temps"] else 0.0
        stage_stats.append(StageTemperatureStat(
            stage_name=stage.name,
            avg_temperature=avg_temp,
            max_deviation=s["max_deviation"],
            violation_count=s["violations"],
            total_readings=s["total"]
        ))

    if len(readings) >= 2:
        first_sg = readings[0].specific_gravity
        last_sg = readings[-1].specific_gravity
        total_sg_drop = round(first_sg - last_sg, 4)
        days = (readings[-1].timestamp - readings[0].timestamp).total_seconds() / 86400.0
        avg_daily_sg_drop = round(total_sg_drop / days, 6) if days > 0 else 0.0
    else:
        total_sg_drop = 0.0
        avg_daily_sg_drop = 0.0

    alert_summary = {
        "total": len(alerts),
        "temperature_deviation": len([a for a in alerts if a.alert_type == AlertType.TEMPERATURE_DEVIATION]),
        "fermentation_stall": len([a for a in alerts if a.alert_type == AlertType.FERMENTATION_STALL]),
        "warning": len([a for a in alerts if a.severity == AlertSeverity.WARNING]),
        "critical": len([a for a in alerts if a.severity == AlertSeverity.CRITICAL]),
    }

    critical_count = alert_summary["critical"]
    quality_grade = compute_quality_grade(total_readings, temp_violations, critical_count)

    report_data_dict = {
        "batch_number": batch.batch_number,
        "recipe_name": batch.recipe.name,
        "recipe_style": batch.recipe.style.value,
        "fermenter_code": batch.fermenter.code,
        "fermenter_location": batch.fermenter.location,
        "start_date": batch.start_date.isoformat() if batch.start_date else None,
        "end_date": batch.end_date.isoformat() if batch.end_date else None,
        "measured_og": batch.measured_og,
        "measured_fg": batch.measured_fg,
        "actual_attenuation": batch.actual_attenuation,
        "target_og": batch.recipe.target_og,
        "target_fg": batch.recipe.target_fg,
        "stage_stats": [s.model_dump() for s in stage_stats],
        "total_sg_drop": total_sg_drop,
        "avg_daily_sg_drop": avg_daily_sg_drop,
        "alert_summary": alert_summary,
        "total_readings": total_readings,
        "temp_violations": temp_violations,
        "temp_violation_rate": round(temp_violations / total_readings * 100, 2) if total_readings > 0 else 0,
        "quality_grade": quality_grade.value,
    }

    report = QualityReport(
        batch_id=batch.id,
        report_data=json.dumps(report_data_dict, ensure_ascii=False),
        quality_grade=quality_grade,
    )
    db.add(report)
    db.flush()
    return report


def parse_quality_report(report: QualityReport, batch: Batch) -> dict:
    data = json.loads(report.report_data)
    return {
        "id": report.id,
        "batch_id": batch.id,
        "batch_number": data["batch_number"],
        "recipe_name": data["recipe_name"],
        "fermenter_code": data["fermenter_code"],
        "start_date": datetime.fromisoformat(data["start_date"]) if data["start_date"] else None,
        "end_date": datetime.fromisoformat(data["end_date"]) if data["end_date"] else None,
        "measured_og": data["measured_og"],
        "measured_fg": data["measured_fg"],
        "actual_attenuation": data["actual_attenuation"],
        "stage_stats": [StageTemperatureStat(**s) for s in data["stage_stats"]],
        "total_sg_drop": data["total_sg_drop"],
        "avg_daily_sg_drop": data["avg_daily_sg_drop"],
        "alert_summary": data["alert_summary"],
        "quality_grade": report.quality_grade,
        "generated_at": report.generated_at,
    }
