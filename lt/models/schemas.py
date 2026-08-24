from pydantic import BaseModel
from typing import List

class CommentItem(BaseModel):
    id: str
    comments: str

class InferenceRequest(BaseModel):
    data: List[CommentItem]

class InsightPredictionItem(BaseModel):
    id: str
    comments: str
    category: str
    sub_category: str = ""
    sentiment: str
    priority: str
    is_gibberish: int
    observation: str
    recommendations: str
    customer_response: str
    confidence_score: str
    voc_translated: str
    status: str

class InsightResponse(BaseModel):
    data: List[InsightPredictionItem]
