from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.models import Recipe, FermentationStage, BeerStyle
from app.schemas import RecipeCreate, RecipeUpdate, RecipeResponse, BeerStyle as BeerStyleSchema

router = APIRouter(prefix="/api/recipes", tags=["啤酒配方管理"])


@router.get("", response_model=List[RecipeResponse])
def list_recipes(
    style: Optional[BeerStyle] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Recipe)
    if style:
        query = query.filter(Recipe.style == style)
    return query.order_by(Recipe.name).all()


@router.get("/{recipe_id}", response_model=RecipeResponse)
def get_recipe(recipe_id: int, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")
    return recipe


@router.post("", response_model=RecipeResponse, status_code=status.HTTP_201_CREATED)
def create_recipe(data: RecipeCreate, db: Session = Depends(get_db)):
    existing = db.query(Recipe).filter(Recipe.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"配方名称 {data.name} 已存在")

    if not data.stages:
        raise HTTPException(status_code=400, detail="至少需要一个发酵阶段")

    recipe = Recipe(
        name=data.name,
        style=data.style,
        target_og=data.target_og,
        target_fg=data.target_fg,
    )
    db.add(recipe)
    db.flush()

    orders_seen = set()
    for stage_data in data.stages:
        if stage_data.order in orders_seen:
            db.rollback()
            raise HTTPException(status_code=400, detail=f"阶段顺序 {stage_data.order} 重复")
        orders_seen.add(stage_data.order)
        stage = FermentationStage(
            recipe_id=recipe.id,
            order=stage_data.order,
            name=stage_data.name,
            target_temperature=stage_data.target_temperature,
            temperature_tolerance=stage_data.temperature_tolerance,
            duration_days=stage_data.duration_days,
        )
        db.add(stage)

    db.commit()
    db.refresh(recipe)
    return recipe


@router.put("/{recipe_id}", response_model=RecipeResponse)
def update_recipe(
    recipe_id: int,
    data: RecipeUpdate,
    db: Session = Depends(get_db)
):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")

    update_data = data.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] != recipe.name:
        existing = db.query(Recipe).filter(Recipe.name == update_data["name"]).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"配方名称 {update_data['name']} 已存在")

    if "stages" in update_data:
        new_stages = update_data.pop("stages")
        if not new_stages:
            raise HTTPException(status_code=400, detail="至少需要一个发酵阶段")

        db.query(FermentationStage).filter(FermentationStage.recipe_id == recipe_id).delete()

        orders_seen = set()
        for stage_data in new_stages:
            if stage_data["order"] in orders_seen:
                db.rollback()
                raise HTTPException(status_code=400, detail=f"阶段顺序 {stage_data['order']} 重复")
            orders_seen.add(stage_data["order"])
            stage = FermentationStage(
                recipe_id=recipe.id,
                order=stage_data["order"],
                name=stage_data["name"],
                target_temperature=stage_data["target_temperature"],
                temperature_tolerance=stage_data["temperature_tolerance"],
                duration_days=stage_data["duration_days"],
            )
            db.add(stage)

    for key, value in update_data.items():
        setattr(recipe, key, value)

    db.commit()
    db.refresh(recipe)
    return recipe


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recipe(recipe_id: int, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="配方不存在")

    if recipe.batches:
        raise HTTPException(
            status_code=400,
            detail=f"配方已被 {len(recipe.batches)} 个批次使用，无法删除"
        )

    db.delete(recipe)
    db.commit()
    return None
