"""Upload and review endpoints.

This is the privacy boundary. Everything returned from here is a response model from
app.schemas.api_models, and none of those carry a raw identifier value. Do not return a
dict you built by hand - go through the response model so the boundary is enforced by
the type, not by whoever is reviewing the pull request.

Owner: Diddekunta Jagan Mohan Reddy
"""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from app.schemas.api_models import ReviewRequest, ReviewResponse

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/review", response_model=ReviewResponse)
async def review_text(request: ReviewRequest) -> ReviewResponse:
    """Review raw or annotated text pasted into the interface."""
    raise NotImplementedError("Review endpoint - planned for Review 2")


@router.post("/upload", response_model=ReviewResponse)
async def review_uploads(files: list[UploadFile] = File(...)) -> ReviewResponse:
    """Review one or more uploaded documents (.txt, .pdf).

    Several files in one call is the multi-document case - it is what makes cross-document
    linkage analysis possible, so keep the batch together rather than looping per file.
    """
    raise NotImplementedError("Upload endpoint - planned for Review 2")
