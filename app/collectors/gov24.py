from __future__ import annotations

from typing import Any

from app.collectors.base import BaseCollector


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
