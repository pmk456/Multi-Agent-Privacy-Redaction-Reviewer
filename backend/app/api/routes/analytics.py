"""Aggregate reporting endpoints. Counts only.

Owner: Diddekunta Jagan Mohan Reddy with Pulagampalli Sai Mahima
"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.api_models import AggregateReport

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/batch/{batch_id}", response_model=AggregateReport)
async def batch_report(batch_id: str) -> AggregateReport:
    raise NotImplementedError("Analytics endpoint - planned for Review 3")
