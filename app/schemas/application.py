from pydantic import BaseModel

from app.schemas.common import (
    ApplicationStep,
    ChecklistItem,
    DocumentStatus,
    PolicyLawItem,
    PolicyLinkItem,
    RequiredDocumentItem,
)


class ApplicationPrepData(BaseModel):
    policy_id: str
    application_step: ApplicationStep
    required_documents: list[RequiredDocumentItem]
    checklist_items: list[ChecklistItem]
    related_links: list[PolicyLinkItem]
    laws: list[PolicyLawItem]
    application_url: str | None = None


class ChecklistPatchRequest(BaseModel):
    is_done: bool


class DocumentPatchRequest(BaseModel):
    status: DocumentStatus
    uploaded_file_url: str | None = None
