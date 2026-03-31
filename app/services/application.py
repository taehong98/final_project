from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AnalysisResultState,
    ApplicationChecklistState,
    ApplicationDocumentState,
    PolicyDocument,
)


DEFAULT_CHECKLISTS = [
    ("INPUT_BASIC_INFO", "신청자 기본 정보 입력 완료", True, 1),
    ("CHECK_POLICY_DETAIL", "정책 상세 내용 확인", True, 2),
    ("PREPARE_REQUIRED_DOCS", "필요 서류 준비", False, 3),
    ("UPLOAD_SUPPORT_DOCS", "증빙 서류 업로드", False, 4),
]


def ensure_application_state(db: Session, policy_id: str) -> tuple[list[ApplicationDocumentState], list[ApplicationChecklistState]]:
    documents = db.execute(
        select(ApplicationDocumentState).where(ApplicationDocumentState.policy_id == policy_id).order_by(ApplicationDocumentState.id)
    ).scalars().all()
    if not documents:
        base_docs = db.execute(select(PolicyDocument).where(PolicyDocument.policy_id == policy_id).order_by(PolicyDocument.id)).scalars().all()
        for doc in base_docs:
            document_type = doc.document_type or f"DOC_{doc.id}"
            default_status = "READY" if doc.document_group in {"submission", "self_verify", "official_verify"} else "MISSING"
            db.add(
                ApplicationDocumentState(
                    policy_id=policy_id,
                    document_type=document_type,
                    document_name=doc.document_name,
                    status=default_status,
                    description=doc.document_description,
                    is_required=doc.is_required,
                    issued_within_days=doc.issued_within_days,
                    updated_at=datetime.utcnow(),
                )
            )
        db.commit()
        documents = db.execute(
            select(ApplicationDocumentState).where(ApplicationDocumentState.policy_id == policy_id).order_by(ApplicationDocumentState.id)
        ).scalars().all()

    checklist = db.execute(
        select(ApplicationChecklistState).where(ApplicationChecklistState.policy_id == policy_id).order_by(ApplicationChecklistState.sort_order)
    ).scalars().all()
    if not checklist:
        for code, label, is_done, sort_order in DEFAULT_CHECKLISTS:
            db.add(
                ApplicationChecklistState(
                    policy_id=policy_id,
                    code=code,
                    label=label,
                    is_done=is_done,
                    sort_order=sort_order,
                    updated_at=datetime.utcnow(),
                )
            )
        db.commit()
        checklist = db.execute(
            select(ApplicationChecklistState).where(ApplicationChecklistState.policy_id == policy_id).order_by(ApplicationChecklistState.sort_order)
        ).scalars().all()

    return documents, checklist


def update_checklist_state(db: Session, policy_id: str, code: str, is_done: bool) -> ApplicationChecklistState | None:
    ensure_application_state(db, policy_id)
    item = db.execute(
        select(ApplicationChecklistState).where(
            ApplicationChecklistState.policy_id == policy_id,
            ApplicationChecklistState.code == code,
        )
    ).scalar_one_or_none()
    if not item:
        return None
    item.is_done = is_done
    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return item


def update_document_state(db: Session, policy_id: str, document_type: str, status: str, uploaded_file_url: str | None) -> ApplicationDocumentState | None:
    ensure_application_state(db, policy_id)
    item = db.execute(
        select(ApplicationDocumentState).where(
            ApplicationDocumentState.policy_id == policy_id,
            ApplicationDocumentState.document_type == document_type,
        )
    ).scalar_one_or_none()
    if not item:
        return None
    item.status = status
    item.uploaded_file_url = uploaded_file_url
    item.updated_at = datetime.utcnow()
    if status == "VERIFIED":
        item.verified_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return item


def get_application_step(db: Session, policy_id: str) -> str:
    result = db.execute(select(AnalysisResultState).where(AnalysisResultState.policy_id == policy_id)).scalar_one_or_none()
    if not result:
        return "DOCUMENT_PREP"
    if result.apply_status == "APPLICABLE_NOW":
        return "DOCUMENT_PREP"
    return "POLICY_SELECTION"
