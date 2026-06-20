from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from enum import Enum
import datetime

from app.database import Base


class FermenterStatus(str, Enum):
    IDLE = "空闲"
    FERMENTING = "发酵中"
    CLEANING = "清洗中"
    FAULTY = "故障"


class BeerStyle(str, Enum):
    IPA = "IPA"
    STOUT = "Stout"
    LAGER = "Lager"
    WHEAT = "Wheat"
    PILSNER = "Pilsner"


class BatchStatus(str, Enum):
    FERMENTING = "发酵中"
    COMPLETED = "已完成"
    ABORTED = "异常终止"


class AlertType(str, Enum):
    TEMPERATURE_DEVIATION = "温度偏差"
    FERMENTATION_STALL = "发酵停滞"


class AlertSeverity(str, Enum):
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    CLOSED = "closed"


class QualityGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class Fermenter(Base):
    __tablename__ = "fermenters"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True, nullable=False)
    capacity = Column(Float, nullable=False)
    status = Column(SQLEnum(FermenterStatus), default=FermenterStatus.IDLE, nullable=False)
    location = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    batches = relationship("Batch", back_populates="fermenter")


class Recipe(Base):
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)
    style = Column(SQLEnum(BeerStyle), nullable=False)
    target_og = Column(Float, nullable=False)
    target_fg = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    stages = relationship("FermentationStage", back_populates="recipe", cascade="all, delete-orphan", order_by="FermentationStage.order")
    batches = relationship("Batch", back_populates="recipe")


class FermentationStage(Base):
    __tablename__ = "fermentation_stages"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    order = Column(Integer, nullable=False)
    name = Column(String(100), nullable=False)
    target_temperature = Column(Float, nullable=False)
    temperature_tolerance = Column(Float, nullable=False)
    duration_days = Column(Integer, nullable=False)

    recipe = relationship("Recipe", back_populates="stages")


class Batch(Base):
    __tablename__ = "batches"

    id = Column(Integer, primary_key=True, index=True)
    batch_number = Column(String(50), unique=True, index=True, nullable=False)
    fermenter_id = Column(Integer, ForeignKey("fermenters.id"), nullable=False)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=True)
    measured_og = Column(Float, nullable=False)
    measured_fg = Column(Float, nullable=True)
    actual_attenuation = Column(Float, nullable=True)
    status = Column(SQLEnum(BatchStatus), default=BatchStatus.FERMENTING, nullable=False)

    fermenter = relationship("Fermenter", back_populates="batches")
    recipe = relationship("Recipe", back_populates="batches")
    readings = relationship("SensorReading", back_populates="batch", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="batch", cascade="all, delete-orphan")
    quality_report = relationship("QualityReport", back_populates="batch", uselist=False, cascade="all, delete-orphan")


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("batches.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    temperature = Column(Float, nullable=False)
    specific_gravity = Column(Float, nullable=False)
    is_abnormal = Column(Integer, default=0, nullable=False)
    stage_name = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    batch = relationship("Batch", back_populates="readings")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    alert_type = Column(SQLEnum(AlertType), nullable=False)
    severity = Column(SQLEnum(AlertSeverity), nullable=False)
    batch_id = Column(Integer, ForeignKey("batches.id"), nullable=False)
    reading_id = Column(Integer, ForeignKey("sensor_readings.id"), nullable=True)
    trigger_value = Column(String(255), nullable=False)
    stage_info = Column(String(255), nullable=True)
    status = Column(SQLEnum(AlertStatus), default=AlertStatus.OPEN, nullable=False)
    triggered_at = Column(DateTime(timezone=True), nullable=False)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    description = Column(Text, nullable=True)

    batch = relationship("Batch", back_populates="alerts")
    reading = relationship("SensorReading")


class QualityReport(Base):
    __tablename__ = "quality_reports"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("batches.id"), unique=True, nullable=False)
    report_data = Column(Text, nullable=False)
    quality_grade = Column(SQLEnum(QualityGrade), nullable=False)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())

    batch = relationship("Batch", back_populates="quality_report")
