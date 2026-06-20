from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import random

from app.models import (
    Fermenter, FermenterStatus, Recipe, FermentationStage, BeerStyle,
    Batch, BatchStatus, SensorReading, Alert, AlertType, AlertSeverity,
    AlertStatus, QualityReport, QualityGrade
)
from app.utils import (
    get_current_stage, check_temperature_deviation,
    check_fermentation_stall, create_temperature_alert,
    create_stall_alert, calculate_actual_attenuation,
    generate_quality_report
)


def create_fermenters(db: Session):
    fermenters_data = [
        {"code": "F-001", "capacity": 500.0, "status": FermenterStatus.IDLE, "location": "A区-1号位"},
        {"code": "F-002", "capacity": 500.0, "status": FermenterStatus.IDLE, "location": "A区-2号位"},
        {"code": "F-003", "capacity": 1000.0, "status": FermenterStatus.FERMENTING, "location": "B区-1号位"},
        {"code": "F-004", "capacity": 1000.0, "status": FermenterStatus.FERMENTING, "location": "B区-2号位"},
        {"code": "F-005", "capacity": 2000.0, "status": FermenterStatus.IDLE, "location": "C区-1号位"},
    ]
    for fd in fermenters_data:
        f = Fermenter(**fd)
        db.add(f)
    db.flush()


def create_recipes(db: Session):
    recipes_data = [
        {
            "name": "经典IPA配方",
            "style": BeerStyle.IPA,
            "target_og": 1.065,
            "target_fg": 1.012,
            "stages": [
                {"order": 1, "name": "接种阶段", "target_temperature": 18.0, "temperature_tolerance": 1.0, "duration_days": 1},
                {"order": 2, "name": "主发酵阶段", "target_temperature": 20.0, "temperature_tolerance": 1.5, "duration_days": 5},
                {"order": 3, "name": "双乙酰还原阶段", "target_temperature": 22.0, "temperature_tolerance": 1.0, "duration_days": 2},
                {"order": 4, "name": "降温熟成阶段", "target_temperature": 4.0, "temperature_tolerance": 2.0, "duration_days": 3},
            ],
        },
        {
            "name": "爱尔兰世涛配方",
            "style": BeerStyle.STOUT,
            "target_og": 1.055,
            "target_fg": 1.015,
            "stages": [
                {"order": 1, "name": "接种阶段", "target_temperature": 19.0, "temperature_tolerance": 1.0, "duration_days": 1},
                {"order": 2, "name": "主发酵阶段", "target_temperature": 21.0, "temperature_tolerance": 1.5, "duration_days": 6},
                {"order": 3, "name": "降温熟成阶段", "target_temperature": 5.0, "temperature_tolerance": 2.0, "duration_days": 3},
            ],
        },
        {
            "name": "波西米亚拉格配方",
            "style": BeerStyle.LAGER,
            "target_og": 1.048,
            "target_fg": 1.010,
            "stages": [
                {"order": 1, "name": "接种阶段", "target_temperature": 10.0, "temperature_tolerance": 0.8, "duration_days": 1},
                {"order": 2, "name": "主发酵阶段", "target_temperature": 12.0, "temperature_tolerance": 1.0, "duration_days": 7},
                {"order": 3, "name": "后熟澄清阶段", "target_temperature": 2.0, "temperature_tolerance": 1.5, "duration_days": 4},
            ],
        },
    ]

    recipes = []
    for rd in recipes_data:
        stages_data = rd.pop("stages")
        r = Recipe(**rd)
        db.add(r)
        db.flush()
        for sd in stages_data:
            s = FermentationStage(recipe_id=r.id, **sd)
            db.add(s)
        recipes.append(r)
    db.flush()
    return recipes


def _build_sg_values(
    og: float,
    fg: float,
    reading_count: int,
    stall_start: int = None,
    stall_length: int = 0,
):
    total_drop = og - fg
    normal_reading_count = reading_count
    if stall_start is not None:
        normal_reading_count = reading_count - stall_length

    sg_drop_normal = total_drop / normal_reading_count if normal_reading_count > 0 else 0

    values = []
    for i in range(reading_count):
        if stall_start is not None and i >= stall_start and i < stall_start + stall_length:
            sg = values[-1] if values else og
        else:
            idx = i
            if stall_start is not None and i >= stall_start + stall_length:
                idx = i - stall_length
            sg = og - sg_drop_normal * (idx + 1)
        values.append(round(sg, 4))

    return values


def _generate_readings_for_batch(
    db: Session,
    batch: Batch,
    interval_hours: int,
    sg_values: list,
    inject_anomaly_at_indices=None,
    inject_stall_indices=None,
):
    if inject_anomaly_at_indices is None:
        inject_anomaly_at_indices = []
    if inject_stall_indices is None:
        inject_stall_indices = []

    recipe = batch.recipe
    start_time = batch.start_date
    reading_count = len(sg_values)

    random.seed(batch.id * 1000 + reading_count)

    readings = []
    for i in range(reading_count):
        ts = start_time + timedelta(hours=i * interval_hours)

        if ts > datetime.now() + timedelta(hours=1):
            break

        stage_result = get_current_stage(batch, ts)
        sg = sg_values[i]

        if stage_result:
            stage, _, _ = stage_result
            target_temp = stage.target_temperature
            tolerance = stage.temperature_tolerance

            if i in inject_anomaly_at_indices:
                temp = target_temp + tolerance * 1.8 + random.uniform(0.5, 1.5)
            else:
                temp = target_temp + random.uniform(-tolerance * 0.5, tolerance * 0.5)
        else:
            temp = 20.0

        is_abnormal = 0
        if i in inject_anomaly_at_indices or i in inject_stall_indices:
            is_abnormal = 1

        reading = SensorReading(
            batch_id=batch.id,
            timestamp=ts,
            temperature=round(temp, 2),
            specific_gravity=sg,
            is_abnormal=is_abnormal,
        )
        if stage_result:
            stage, _, _ = stage_result
            reading.stage_name = stage.name
        db.add(reading)
        readings.append(reading)
    db.flush()

    for reading in readings:
        stage_result = get_current_stage(batch, reading.timestamp)
        if stage_result:
            stage, _, _ = stage_result
            is_temp_violation, severity, deviation = check_temperature_deviation(
                reading.temperature, stage
            )
            if is_temp_violation:
                existing = (
                    db.query(Alert)
                    .filter(
                        Alert.batch_id == batch.id,
                        Alert.reading_id == reading.id,
                        Alert.alert_type == AlertType.TEMPERATURE_DEVIATION,
                    )
                    .first()
                )
                if not existing:
                    create_temperature_alert(db, batch, reading, stage, deviation, severity)

    db.flush()

    for idx in inject_stall_indices:
        if idx < len(readings):
            reading = readings[idx]
            stall_count = len([x for x in inject_stall_indices if x <= idx])
            severity = AlertSeverity.CRITICAL if stall_count >= 5 else AlertSeverity.WARNING
            create_stall_alert(db, batch, reading, stall_count, severity)

    db.flush()
    return readings


def create_active_batches(db: Session, recipes):
    now = datetime.now()
    ipa_recipe = recipes[0]
    stout_recipe = recipes[1]

    fermenter3 = db.query(Fermenter).filter(Fermenter.code == "F-003").first()
    fermenter4 = db.query(Fermenter).filter(Fermenter.code == "F-004").first()

    batch1_start = now - timedelta(days=3, hours=6)
    batch1_number = f"B{batch1_start.strftime('%Y%m%d')}-001"

    batch1 = Batch(
        batch_number=batch1_number,
        fermenter_id=fermenter3.id,
        recipe_id=ipa_recipe.id,
        start_date=batch1_start,
        measured_og=1.0648,
        status=BatchStatus.FERMENTING,
    )
    db.add(batch1)
    db.flush()

    elapsed_hours_1 = int((now - batch1_start).total_seconds() / 3600)
    reading_count_1 = elapsed_hours_1 // 8
    sg_values_1 = _build_sg_values(1.0648, 1.012, reading_count_1)

    _generate_readings_for_batch(
        db, batch1,
        interval_hours=8,
        sg_values=sg_values_1,
        inject_anomaly_at_indices=[5, min(13, reading_count_1 - 2)],
    )

    batch2_start = now - timedelta(days=4, hours=12)
    batch2_number = f"B{batch2_start.strftime('%Y%m%d')}-001"
    if batch2_number == batch1_number:
        batch2_number = f"B{batch2_start.strftime('%Y%m%d')}-002"

    batch2 = Batch(
        batch_number=batch2_number,
        fermenter_id=fermenter4.id,
        recipe_id=stout_recipe.id,
        start_date=batch2_start,
        measured_og=1.0547,
        status=BatchStatus.FERMENTING,
    )
    db.add(batch2)
    db.flush()

    elapsed_hours_2 = int((now - batch2_start).total_seconds() / 3600)
    reading_count_2 = elapsed_hours_2 // 8
    sg_values_2 = _build_sg_values(1.0547, 1.015, reading_count_2)

    _generate_readings_for_batch(
        db, batch2,
        interval_hours=8,
        sg_values=sg_values_2,
        inject_anomaly_at_indices=[7, min(16, reading_count_2 - 2)],
    )

    db.flush()
    return [batch1, batch2]


def create_completed_batch(db: Session, recipes):
    lager_recipe = recipes[2]
    fermenter1 = db.query(Fermenter).filter(Fermenter.code == "F-001").first()

    start = datetime.now() - timedelta(days=30)
    end = start + timedelta(days=12)

    batch_number = f"B{start.strftime('%Y%m%d')}-001"

    measured_og = 1.0478
    measured_fg = 1.0105
    actual_attenuation = calculate_actual_attenuation(measured_og, measured_fg)

    batch = Batch(
        batch_number=batch_number,
        fermenter_id=fermenter1.id,
        recipe_id=lager_recipe.id,
        start_date=start,
        end_date=end,
        measured_og=measured_og,
        measured_fg=measured_fg,
        actual_attenuation=actual_attenuation,
        status=BatchStatus.COMPLETED,
    )
    db.add(batch)
    db.flush()

    sg_values = _build_sg_values(
        measured_og, measured_fg,
        reading_count=25,
        stall_start=20,
        stall_length=3,
    )

    _generate_readings_for_batch(
        db, batch,
        interval_hours=10,
        sg_values=sg_values,
        inject_anomaly_at_indices=[8, 17],
        inject_stall_indices=[21, 22, 23],
    )

    report = generate_quality_report(db, batch)
    db.flush()

    return batch


def seed_database(db: Session):
    fermenter_count = db.query(Fermenter).count()
    if fermenter_count > 0:
        return False

    create_fermenters(db)
    recipes = create_recipes(db)
    create_active_batches(db, recipes)
    create_completed_batch(db, recipes)

    db.commit()
    return True
