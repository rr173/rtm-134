from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
from enum import Enum

from app.models import (
    FermenterStatus, BeerStyle, BatchStatus,
    AlertType, AlertSeverity, AlertStatus, QualityGrade
)


class FermenterBase(BaseModel):
    code: str = Field(..., description="发酵罐编号")
    capacity: float = Field(..., description="容量(升)")
    status: FermenterStatus = Field(default=FermenterStatus.IDLE, description="状态")
    location: str = Field(..., description="安装位置")


class FermenterCreate(FermenterBase):
    pass


class FermenterUpdate(BaseModel):
    code: Optional[str] = None
    capacity: Optional[float] = None
    status: Optional[FermenterStatus] = None
    location: Optional[str] = None


class FermenterResponse(FermenterBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class FermentationStageBase(BaseModel):
    name: str = Field(..., description="阶段名称")
    target_temperature: float = Field(..., description="目标温度(摄氏度)")
    temperature_tolerance: float = Field(..., description="允许偏差(正负度)")
    duration_days: int = Field(..., description="持续天数")


class FermentationStageCreate(FermentationStageBase):
    order: int = Field(..., description="阶段顺序")


class FermentationStageResponse(FermentationStageBase):
    id: int
    order: int

    class Config:
        from_attributes = True


class RecipeBase(BaseModel):
    name: str = Field(..., description="配方名称")
    style: BeerStyle = Field(..., description="啤酒风格")
    target_og: float = Field(..., description="目标初始比重")
    target_fg: float = Field(..., description="目标终末比重")


class RecipeCreate(RecipeBase):
    stages: List[FermentationStageCreate] = Field(..., description="温度曲线阶段")


class RecipeUpdate(BaseModel):
    name: Optional[str] = None
    style: Optional[BeerStyle] = None
    target_og: Optional[float] = None
    target_fg: Optional[float] = None
    stages: Optional[List[FermentationStageCreate]] = None


class RecipeResponse(RecipeBase):
    id: int
    created_at: datetime
    stages: List[FermentationStageResponse]

    class Config:
        from_attributes = True


class BatchBase(BaseModel):
    pass


class BatchStartRequest(BaseModel):
    fermenter_id: int = Field(..., description="发酵罐ID")
    recipe_id: int = Field(..., description="配方ID")
    measured_og: float = Field(..., description="初始比重实测值")
    start_date: Optional[datetime] = Field(default=None, description="投料日期(默认当前时间)")


class BatchEndRequest(BaseModel):
    measured_fg: float = Field(..., description="终末比重实测值")
    end_date: Optional[datetime] = Field(default=None, description="结束日期(默认当前时间)")


class BatchResponse(BaseModel):
    id: int
    batch_number: str
    fermenter_id: int
    recipe_id: int
    start_date: datetime
    end_date: Optional[datetime]
    measured_og: float
    measured_fg: Optional[float]
    actual_attenuation: Optional[float]
    status: BatchStatus
    fermenter: Optional[FermenterResponse] = None
    recipe: Optional[RecipeResponse] = None

    class Config:
        from_attributes = True


class SensorReadingCreate(BaseModel):
    timestamp: Optional[datetime] = Field(default=None, description="读数时间戳(默认当前时间)")
    temperature: float = Field(..., description="温度值(摄氏度)")
    specific_gravity: float = Field(..., description="比重值")


class SensorReadingResponse(BaseModel):
    id: int
    batch_id: int
    timestamp: datetime
    temperature: float
    specific_gravity: float
    is_abnormal: int
    stage_name: Optional[str]

    class Config:
        from_attributes = True


class AlertBase(BaseModel):
    pass


class AlertUpdate(BaseModel):
    status: Optional[AlertStatus] = None


class AlertResponse(BaseModel):
    id: int
    alert_type: AlertType
    severity: AlertSeverity
    batch_id: int
    reading_id: Optional[int]
    trigger_value: str
    stage_info: Optional[str]
    status: AlertStatus
    triggered_at: datetime
    acknowledged_at: Optional[datetime]
    closed_at: Optional[datetime]
    description: Optional[str]

    class Config:
        from_attributes = True


class FermentationProgressResponse(BaseModel):
    batch_id: int
    batch_number: str
    current_stage: Optional[str]
    stage_elapsed_days: float
    temperature_deviation: Optional[float]
    current_sg: Optional[float]
    sg_to_fg_distance: Optional[float]
    remaining_days_estimate: float
    alert_count: int


class StageTemperatureStat(BaseModel):
    stage_name: str
    avg_temperature: float
    max_deviation: float
    violation_count: int
    total_readings: int


class QualityReportResponse(BaseModel):
    id: int
    batch_id: int
    batch_number: str
    recipe_name: str
    fermenter_code: str
    start_date: datetime
    end_date: datetime
    measured_og: float
    measured_fg: float
    actual_attenuation: float
    stage_stats: List[StageTemperatureStat]
    total_sg_drop: float
    avg_daily_sg_drop: float
    alert_summary: dict
    quality_grade: QualityGrade
    generated_at: datetime


class FermenterUtilization(BaseModel):
    fermenter_id: int
    fermenter_code: str
    total_days: int
    fermenting_days: int
    utilization_rate: float


class RecipeStat(BaseModel):
    recipe_id: int
    recipe_name: str
    style: BeerStyle
    batch_count: int
    avg_attenuation: Optional[float]
    avg_grade_score: Optional[float]


class AlertFrequencyByRecipe(BaseModel):
    recipe_id: int
    recipe_name: str
    style: BeerStyle
    total_alerts: int
    temperature_alerts: int
    stall_alerts: int
    critical_alerts: int
    batch_count: int
    alerts_per_batch: float
