"""Schemas for apply-assist endpoints."""

from typing import List

from pydantic import BaseModel

from .common import DocumentStatusEnum, StepStatusEnum


class FlowStep(BaseModel):
    step: int
    label: str
    status: StepStatusEnum


class DocumentCard(BaseModel):
    doc_id: str
    icon: str
    name: str
    status: DocumentStatusEnum
    status_label: str
    description: str


class ChecklistItem(BaseModel):
    item_id: str
    label: str
    done: bool


class ApplyMeta(BaseModel):
    policy_name: str
    apply_url: str
    source_label: str


class ApplyAssistData(BaseModel):
    flow_steps: List[FlowStep]
    document_cards: List[DocumentCard]
    checklist: List[ChecklistItem]
    apply_meta: ApplyMeta


class ApplyAssistResponse(BaseModel):
    apply_assist_data: ApplyAssistData
