from fastapi import FastAPI

from app.schemas import AnalyzeRequest, AnalyzeResponse
from app.domain.scoring import analyze

app = FastAPI(title="AI Visibility Scoring MVP", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze-business", response_model=AnalyzeResponse)
def analyze_business(payload: AnalyzeRequest) -> AnalyzeResponse:
    return analyze(payload.business_name, payload.location, payload.trade)
