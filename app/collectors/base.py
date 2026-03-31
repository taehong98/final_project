from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import httpx
import xmltodict
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    RawApiFetchLog,
    RawPolicyConditionItem,
    RawPolicyDetailItem,
    RawPolicyListItem,
    RawPolicySubresourceItem,
)


class CollectorError(Exception):
    pass


class BaseCollector:
    source_name: str

    def __init__(
        self,
        db: Session,
        service_key: str,
        base_url: str,
        timeout_seconds: int = 30,
        max_retries: int = 4,
        retry_backoff_seconds: float = 1.5,
    ):
        self.db = db
        self.service_key = service_key
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout_seconds)
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds

    def close(self) -> None:
        self.client.close()

    def _build_url(self, endpoint: str) -> str:
        return f"{self.base_url}/{endpoint.lstrip('/')}"

    def _decode_response(self, response: httpx.Response) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "").lower()
        text = response.text.strip()

        if "json" in content_type or text.startswith("{") or text.startswith("["):
            payload = response.json()
            if isinstance(payload, list):
                return {"items": payload}
            return payload

        if "xml" in content_type or text.startswith("<"):
            parsed = xmltodict.parse(text)
            if isinstance(parsed, dict):
                return parsed
            return {"items": parsed}

        return {"raw_text": text}

    def _hash_payload(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _log_fetch(
        self,
        endpoint_name: str,
        request_url: str,
        request_params: dict[str, Any],
        fetched_at: datetime,
        *,
        response_status_code: int | None,
        response_meta_json: dict[str, Any] | None,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        self.db.add(
            RawApiFetchLog(
                source=self.source_name,
                endpoint_name=endpoint_name,
                request_url=request_url,
                request_params_json=request_params,
                response_status_code=response_status_code,
                response_meta_json=response_meta_json,
                fetched_at=fetched_at,
                success_yn=success,
                error_message=error_message,
            )
        )
        self.db.commit()

    def _request(self, endpoint_name: str, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        url = self._build_url(endpoint)
        fetched_at = datetime.utcnow()
        attempts = max(1, self.max_retries)

        for attempt in range(1, attempts + 1):
            response: httpx.Response | None = None
            try:
                response = self.client.get(url, params=params)
                should_retry = response.status_code in {429, 500, 502, 503, 504} and attempt < attempts
                if should_retry:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else self.retry_backoff_seconds * attempt
                    time.sleep(delay)
                    continue

                payload = self._decode_response(response)
                meta = {
                    "headers": dict(response.headers),
                    "query_string": urlencode({k: v for k, v in params.items() if v is not None}),
                    "attempt": attempt,
                }
                self._log_fetch(
                    endpoint_name,
                    request_url=str(response.request.url),
                    request_params=params,
                    fetched_at=fetched_at,
                    response_status_code=response.status_code,
                    response_meta_json=meta,
                    success=response.is_success,
                    error_message=None if response.is_success else response.text[:1000],
                )
                response.raise_for_status()
                return payload
            except Exception as exc:
                is_retryable_error = isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))
                if not is_retryable_error and isinstance(exc, httpx.HTTPStatusError):
                    is_retryable_error = exc.response.status_code in {429, 500, 502, 503, 504}

                if is_retryable_error and attempt < attempts:
                    time.sleep(self.retry_backoff_seconds * attempt)
                    continue

                self._log_fetch(
                    endpoint_name,
                    request_url=str(response.request.url) if response is not None else url,
                    request_params=params,
                    fetched_at=fetched_at,
                    response_status_code=response.status_code if response is not None else None,
                    response_meta_json={"attempt": attempt} if response is None else None,
                    success=False,
                    error_message=str(exc),
                )
                raise CollectorError(f"{self.source_name}:{endpoint_name} request failed") from exc

        raise CollectorError(f"{self.source_name}:{endpoint_name} request failed")

    def _extract_policy_id(self, item: dict[str, Any]) -> str | None:
        for key in (
            "serviceId",
            "servId",
            "svcId",
            "service_id",
            "serv_id",
            "id",
            "서비스ID",
            "서비스아이디",
            "복지서비스ID",
        ):
            value = item.get(key)
            if value:
                return str(value)
        return None

    def _normalize_list(self, payload: dict[str, Any], candidate_keys: tuple[str, ...]) -> list[dict[str, Any]]:
        for key in candidate_keys:
            node = payload.get(key)
            if isinstance(node, list):
                return [item for item in node if isinstance(item, dict)]
            if isinstance(node, dict):
                for nested in node.values():
                    if isinstance(nested, list):
                        return [item for item in nested if isinstance(item, dict)]
        return []

    def _save_unique(self, obj: Any) -> None:
        self.db.add(obj)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()

    def save_list_items(self, page_no: int | None, items: list[dict[str, Any]]) -> int:
        saved = 0
        for item in items:
            source_policy_id = self._extract_policy_id(item)
            if not source_policy_id:
                continue
            self._save_unique(
                RawPolicyListItem(
                    source=self.source_name,
                    source_policy_id=source_policy_id,
                    page_no=page_no,
                    raw_json=item,
                    raw_hash=self._hash_payload(item),
                )
            )
            saved += 1
        return saved

    def save_detail_item(self, source_policy_id: str, payload: dict[str, Any]) -> None:
        self._save_unique(
            RawPolicyDetailItem(
                source=self.source_name,
                source_policy_id=source_policy_id,
                raw_json=payload,
                raw_hash=self._hash_payload(payload),
            )
        )

    def save_condition_item(self, source_policy_id: str, payload: dict[str, Any]) -> None:
        self._save_unique(
            RawPolicyConditionItem(
                source=self.source_name,
                source_policy_id=source_policy_id,
                raw_json=payload,
                raw_hash=self._hash_payload(payload),
            )
        )

    def save_subresource_item(
        self,
        source_policy_id: str,
        subresource_type: str,
        payload: dict[str, Any] | list[dict[str, Any]],
    ) -> None:
        wrapped = payload if isinstance(payload, dict) else {"items": payload}
        self._save_unique(
            RawPolicySubresourceItem(
                source=self.source_name,
                source_policy_id=source_policy_id,
                subresource_type=subresource_type,
                raw_json=wrapped,
                raw_hash=self._hash_payload(wrapped),
            )
        )
