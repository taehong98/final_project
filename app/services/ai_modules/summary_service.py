from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from dotenv import load_dotenv

from .policy_heuristics import (
    assemble_korean_summary,
    choose_better_value,
    clean_fact_value,
    extract_policy_facts,
)
from .prompt_builder import PromptBuilder
from .text_preprocessor import clean_policy_text


class PolicySummaryService:
    SUMMARY_FIELDS = (
        "policy_name",
        "target",
        "benefit",
        "conditions",
        "how_to_apply",
    )

    def __init__(
        self,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        prompt_path: Optional[str] = None,
    ) -> None:
        load_dotenv()

        self.model_name = model_name or os.getenv("QWEN_MODEL", "qwen3.5:4b")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.timeout = float(timeout or os.getenv("OLLAMA_TIMEOUT", "300"))
        self.prompt_path = prompt_path or os.getenv("SUMMARY_PROMPT_PATH", "prompts/prompt_summary.txt")

        prompt_dir = os.path.dirname(self.prompt_path) or "prompts"
        summary_filename = os.path.basename(self.prompt_path) or "prompt_summary.txt"
        self.prompt_builder = PromptBuilder(prompt_dir=prompt_dir, summary_filename=summary_filename)

        print(f"Summary model ready: {self.model_name}")

    def _post_to_ollama(self, payload: Dict) -> Dict:
        url = self.base_url + "/api/chat"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Ollama HTTP error: {exc.code} / {body}") from exc
        except Exception as exc:
            raise RuntimeError(f"Failed to call Ollama: {exc}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to parse Ollama response: {raw[:500]}") from exc

    def _call_model_json(self, messages: List[Dict[str, str]], schema: Dict) -> Dict:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": schema,
            "options": {"temperature": 0},
        }

        outer = self._post_to_ollama(payload)
        content = str(outer.get("message", {}).get("content", "")).strip()
        if not content:
            raise RuntimeError(f"Empty model response: {json.dumps(outer, ensure_ascii=False)[:500]}")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to parse summary JSON: {content}") from exc

        if not isinstance(parsed, dict):
            raise RuntimeError(f"Unexpected summary payload: {parsed}")
        return parsed

    @staticmethod
    def _looks_like_korean(text: str) -> bool:
        return bool(re.search(r"[\uAC00-\uD7A3]", str(text or "")))

    @staticmethod
    def _clip_text(text: str, limit: int = 140) -> str:
        compact = re.sub(r"\s+", " ", str(text or "").strip())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 1].rstrip() + "…"

    def _merge_fields(self, model_data: Dict, heuristic_facts: Dict[str, str]) -> Dict[str, str]:
        merged: Dict[str, str] = {}
        for field in self.SUMMARY_FIELDS:
            merged[field] = choose_better_value(
                str(model_data.get(field, "")),
                heuristic_facts.get(field, ""),
            )
            merged[field] = self._clip_text(clean_fact_value(merged[field]))

        if not merged["benefit"]:
            merged["benefit"] = self._clip_text(
                choose_better_value(
                    heuristic_facts.get("benefit", ""),
                    heuristic_facts.get("summary", ""),
                )
            )

        if not merged["conditions"]:
            merged["conditions"] = self._clip_text(heuristic_facts.get("conditions", ""))

        if not merged["how_to_apply"]:
            merged["how_to_apply"] = self._clip_text(heuristic_facts.get("how_to_apply", ""))

        return merged

    def summarize_policy(self, policy_text: str) -> Dict[str, str]:
        raw_policy_text = str(policy_text or "").strip()
        if not raw_policy_text:
            raise ValueError("policy_text is empty.")

        cleaned_policy_text = clean_policy_text(raw_policy_text)
        heuristic_facts = extract_policy_facts(cleaned_policy_text or raw_policy_text)
        fallback_fields = self._merge_fields({}, heuristic_facts)
        fallback_summary = assemble_korean_summary(fallback_fields)

        model_data: Dict[str, str] = {}
        if cleaned_policy_text:
            try:
                messages = self.prompt_builder.build_summary_messages(cleaned_policy_text)
                schema = self.prompt_builder.get_summary_schema()
                model_data = self._call_model_json(messages, schema)
            except Exception:
                model_data = {}

        merged_fields = self._merge_fields(model_data, heuristic_facts)
        summary = assemble_korean_summary(merged_fields) or fallback_summary
        if not summary:
            summary = self._clip_text(cleaned_policy_text or raw_policy_text, limit=180)

        if not self._looks_like_korean(summary):
            summary = fallback_summary or self._clip_text(cleaned_policy_text or raw_policy_text, limit=180)

        if not summary:
            raise RuntimeError("Summary generation failed.")

        return {
            "language": "ko",
            "summary": summary,
            "summary_source": "qwen" if model_data else "heuristic",
            "policy_name": merged_fields["policy_name"],
            "target": merged_fields["target"],
            "benefit": merged_fields["benefit"],
            "conditions": merged_fields["conditions"],
            "how_to_apply": merged_fields["how_to_apply"],
        }
