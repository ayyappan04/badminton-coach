from typing import Optional
from sqlalchemy import String, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase


class Drill(TimestampedBase):
    __tablename__ = "drills"

    name: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    target_issue_tags: Mapped[list] = mapped_column(JSON, default=list)
    difficulty: Mapped[str] = mapped_column(String, default="all_levels")


class TechniqueReference(TimestampedBase):
    __tablename__ = "technique_references"

    shot_or_movement_name: Mapped[str] = mapped_column(String, index=True)
    singles_or_doubles_context: Mapped[str] = mapped_column(String, default="both")
    summary: Mapped[str] = mapped_column(Text)
    phases: Mapped[list] = mapped_column(JSON, default=list)
    common_beginner_mistakes: Mapped[list] = mapped_column(JSON, default=list)
    advanced_variations: Mapped[list] = mapped_column(JSON, default=list)
    # V2 Comparison Studio fields
    category: Mapped[str] = mapped_column(String, default="shot")  # shot | movement
    checkpoints: Mapped[list] = mapped_column(JSON, default=list)  # per-phase body-position checkpoints
    level_notes: Mapped[dict] = mapped_column(JSON, default=dict)  # {beginner, intermediate, advanced}
    context_notes: Mapped[dict] = mapped_column(JSON, default=dict)  # {attacking, defensive, front_court, rear_court}
