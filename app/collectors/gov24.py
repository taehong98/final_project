from __future__ import annotations

from typing import Any

from app.collectors.base import BaseCollector
from app.collectors.base import CollectorError


class Gov24Collector(BaseCollector):
    source_name = "gov24"

    def fetch_list(self, page: int = 1, per_page: int = 100) -> list[dict[str, Any]]:
        payload = self._request(
            endpoint_name="service_list",
            endpoint="serviceList",
            params={
                "serviceKey": self.service_key,
                "page": page,
                "perPage": per_page,
                "returnType": "JSON",
            },
        )
        items = self._normalize_list(payload, ("data", "serviceList", "items"))
        self.save_list_items(page_no=page, items=items)
        return items

    def fetch_detail(self, source_policy_id: str) -> dict[str, Any]:
        payload = self._request(
            endpoint_name="service_detail",
            endpoint="serviceDetail",
            params={
                "serviceKey": self.service_key,
                "serviceId": source_policy_id,
                "returnType": "JSON",
            },
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        rows: list[dict[str, Any]] = []
        if isinstance(data, list):
            rows = [item for item in data if isinstance(item, dict)]
        elif isinstance(data, dict):
            rows = [data]
        matched_row = None
        for row in rows:
            returned_service_id = row.get("서비스ID") or row.get("serviceId") or row.get("servId")
            if returned_service_id and str(returned_service_id) == str(source_policy_id):
                matched_row = row
                break
        if rows and not matched_row:
            raise CollectorError(
                f"gov24:service_detail returned no matching service id for requested {source_policy_id}"
            )
        self.save_detail_item(source_policy_id=source_policy_id, payload=payload)
        return payload

    def fetch_conditions(self, page: int = 1, per_page: int = 100) -> list[dict[str, Any]]:
        payload = self._request(
            endpoint_name="support_conditions",
            endpoint="supportConditions",
            params={
                "serviceKey": self.service_key,
                "page": page,
                "perPage": per_page,
                "returnType": "JSON",
            },
        )
        items = self._normalize_list(payload, ("data", "supportConditions", "items"))
        for item in items:
            source_policy_id = self._extract_policy_id(item)
            if not source_policy_id:
                continue
            self.save_condition_item(source_policy_id=source_policy_id, payload=item)
        return items
