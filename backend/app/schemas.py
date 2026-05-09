from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    business_name: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)
    trade: str | None = None
    website_url: str | None = None


class CategoryScores(BaseModel):
    ai_presence: int
    seo_strength: int
    authority: int
    performance: int


class Competitor(BaseModel):
    name: str
    score: int


class AnalyzeResponse(BaseModel):
    score: int
    gaps: list[str]
    summary: str
    category_scores: CategoryScores
    competitors: list[Competitor]
    trade: str | None = None
