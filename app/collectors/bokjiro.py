from __future__ import annotations

from typing import Any

from app.collectors.base import BaseCollector


class BokjiroCollector(BaseCollector):
    source_name = "bokjiro"
    list_endpoint = "NationalWelfarelistV001"
    detail_endpoint = "NationalWelfaredetailedV001"

    def _extract_wanted_list(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        candidate_roots = (
            payload.get("wantedList"),
            payload.get("response"),
            payload.get("OpenAPI_ServiceResponse"),
        )
        for root in candidate_roots:
            if isinstance(root, dict):
                serv_list = root.get("servList")
                if isinstance(serv_list, list):
                    return [item for item in serv_list if isinstance(item, dict)]
                if isinstance(serv_list, dict):
                    return [serv_list]
                for nested in root.values():
                    if isinstance(nested, dict):
                        serv_list = nested.get("servList")
                        if isinstance(serv_list, list):
                            return [item for item in serv_list if isinstance(item, dict)]
                        if isinstance(serv_list, dict):
                            return [serv_list]
        return []

    def _extract_subresources(self, detail_payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        subresources: dict[str, list[dict[str, Any]]] = {}
        root_candidates = (
            detail_payload.get("wantedDtl"),
            detail_payload.get("response"),
            detail_payload.get("OpenAPI_ServiceResponse"),
        )

        for root in root_candidates:
            if not isinstance(root, dict):
                continue
            for key in ("applmetList", "inqplCtadrList", "inqplHmpgReldList", "basfrmList", "baslawList"):
                value = root.get(key)
                if isinstance(value, list):
                    subresources[key] = [item for item in value if isinstance(item, dict)]
                elif isinstance(value, dict):
                    subresources[key] = [value]
        return subresources

    def fetch_list(self, page: int = 1, num_rows: int = 100, search_keyword: str | None = None) -> list[dict[str, Any]]:
        payload = self._request(
            endpoint_name="welfare_list",
            endpoint=self.list_endpoint,
            params={
                "serviceKey": self.service_key,
                "callTp": "L",
                "pageNo": page,
                "numOfRows": num_rows,
                "srchKeyCode": "001",
                "searchWrd": search_keyword,
            },
        )
        items = self._extract_wanted_list(payload)
        self.save_list_items(page_no=page, items=items)
        return items

    def fetch_detail(self, source_policy_id: str) -> dict[str, Any]:
        payload = self._request(
            endpoint_name="welfare_detail",
            endpoint=self.detail_endpoint,
            params={
                "serviceKey": self.service_key,
                "callTp": "D",
                "servId": source_policy_id,
            },
        )
        self.save_detail_item(source_policy_id=source_policy_id, payload=payload)

        for subresource_type, subresource_items in self._extract_subresources(payload).items():
            self.save_subresource_item(
                source_policy_id=source_policy_id,
                subresource_type=subresource_type,
                payload=subresource_items,
            )
        return payload
