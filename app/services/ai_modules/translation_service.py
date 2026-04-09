from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv

from .policy_heuristics import (
    count_preserve_tokens,
    protect_special_tokens,
    restore_special_tokens,
)
from .prompt_builder import PromptBuilder
from .text_preprocessor import clean_policy_text


class PolicyTranslationService:
    SOURCE_TERM_COL = "\uD589\uC815 \uC6A9\uC5B4"
    GLOSSARY_COL_MAP = {
        "en": "\uC601\uC5B4",
        "vi": "\uBCA0\uD2B8\uB0A8\uC5B4",
        "zh": "\uC911\uAD6D\uC5B4",
        "ja": "\uC77C\uBCF8\uC5B4",
    }
    REQUIRED_COLUMNS = [SOURCE_TERM_COL, *GLOSSARY_COL_MAP.values()]
    LANG_MAP = {
        "ko": "Korean",
        "en": "English",
        "vi": "Vietnamese",
        "zh": "Chinese",
        "ja": "Japanese",
    }
    MANWON_RE = re.compile(r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*\uB9CC\uC6D0")
    WON_RE = re.compile(r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*\uC6D0")

    def __init__(
        self,
        csv_path: str = "benepick_dict.csv",
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        prompt_path: Optional[str] = None,
    ) -> None:
        load_dotenv()

        self.model_name = model_name or os.getenv("QWEN_MODEL", "qwen3.5:4b")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.timeout = float(timeout or os.getenv("OLLAMA_TIMEOUT", "300"))
        self.prompt_path = prompt_path or os.getenv("TRANSLATION_PROMPT_PATH", "prompts/prompt_translation.txt")

        self.glossary_df = self._load_glossary(csv_path)
        self.prompt_builder = self._build_prompt_builder()
        print(f"Translation model ready: {self.model_name}")

    def _build_prompt_builder(self) -> PromptBuilder:
        prompt_dir = os.path.dirname(self.prompt_path) or "prompts"
        translation_filename = os.path.basename(self.prompt_path) or "prompt_translation.txt"
        return PromptBuilder(prompt_dir=prompt_dir, translation_filename=translation_filename)

    def _load_glossary(self, csv_path: str) -> pd.DataFrame:
        try:
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            df = pd.read_csv(csv_path, encoding="cp949")

        missing = [col for col in self.REQUIRED_COLUMNS if col not in df.columns]
        if missing:
            raise ValueError(f"Missing glossary columns: {missing}")

        df = df[self.REQUIRED_COLUMNS].fillna("")
        for col in self.REQUIRED_COLUMNS:
            df[col] = df[col].astype(str).str.strip()
        df = df[df[self.SOURCE_TERM_COL] != ""].reset_index(drop=True)
        return df

    @staticmethod
    def _normalize_text(text: str) -> str:
        compact = str(text or "").strip()
        compact = re.sub(r"\s+", " ", compact)
        return compact

    def _extract_relevant_glossary(self, text: str, policy_text: str, target_lang: str) -> str:
        if target_lang == "ko":
            return ""

        target_col = self.GLOSSARY_COL_MAP[target_lang]
        combined_text = f"{text}\n{policy_text}"
        matches: list[tuple[str, str]] = []

        for _, row in self.glossary_df.iterrows():
            term = str(row[self.SOURCE_TERM_COL]).strip()
            translated = str(row[target_col]).strip()
            if not term or not translated:
                continue
            if term in combined_text:
                matches.append((term, translated))

        matches.sort(key=lambda item: len(item[0]), reverse=True)
        limited = matches[:12]
        return "\n".join(f"- {term} -> {translated}" for term, translated in limited)

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
        return self._call_model_json_for_model(self.model_name, messages, schema)

    def _call_model_json_for_model(self, model_name: str, messages: List[Dict[str, str]], schema: Dict) -> Dict:
        payload = {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": schema,
            "options": {"temperature": 0},
        }
        outer = self._post_to_ollama(payload)
        content = str(outer.get("message", {}).get("content", "")).strip()
        if not content:
            raise RuntimeError("Empty translation response.")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to parse translation JSON: {content}") from exc

        if not isinstance(parsed, dict):
            raise RuntimeError(f"Unexpected translation payload: {parsed}")

        normalized = dict(parsed)
        if not str(normalized.get("translated_text", "")).strip():
            for key in ("translation", "translated", "result", "text", "title"):
                candidate = str(normalized.get(key, "")).strip()
                if candidate:
                    normalized["translated_text"] = candidate
                    break

        if not str(normalized.get("translated_text", "")).strip():
            string_values = [str(value).strip() for value in normalized.values() if isinstance(value, str) and str(value).strip()]
            if len(string_values) == 1:
                normalized["translated_text"] = string_values[0]

        return normalized

    @staticmethod
    def _format_number(value: float, target_lang: str) -> str:
        rounded = int(round(value))
        if target_lang == "vi":
            return f"{rounded:,}".replace(",", ".")
        return f"{rounded:,}"

    def _localize_money_units(self, text: str, target_lang: str) -> str:
        if target_lang == "ko":
            return text

        def replace_manwon(match: re.Match[str]) -> str:
            raw_value = match.group("num").replace(",", "")
            try:
                numeric = float(raw_value)
            except ValueError:
                return match.group(0)

            if target_lang == "zh":
                return f"{match.group('num')}万韩元"
            if target_lang == "ja":
                return f"{match.group('num')}万ウォン"
            return f"{self._format_number(numeric * 10000, target_lang)} KRW"

        def replace_won(match: re.Match[str]) -> str:
            raw_value = match.group("num").replace(",", "")
            try:
                numeric = float(raw_value)
            except ValueError:
                return match.group(0)

            if target_lang == "zh":
                return f"{match.group('num')}韩元"
            if target_lang == "ja":
                return f"{match.group('num')}ウォン"
            return f"{self._format_number(numeric, target_lang)} KRW"

        localized = self.MANWON_RE.sub(replace_manwon, text)
        localized = self.WON_RE.sub(replace_won, localized)
        localized = localized.replace("韩元元", "韩元")
        localized = localized.replace("ウォンウォン", "ウォン")
        localized = localized.replace("KRW KRW", "KRW")
        return localized

    def _candidate_models(self, target_lang: str) -> List[str]:
        candidates: list[str] = []

        env_specific = os.getenv(f"QWEN_TRANSLATION_MODEL_{target_lang.upper()}")
        env_generic = os.getenv("QWEN_TRANSLATION_MODEL")

        if env_specific:
            candidates.append(env_specific)
        if target_lang in {"zh", "ja"}:
            candidates.append("qwen3:4b")
        if env_generic:
            candidates.append(env_generic)
        candidates.append(self.model_name)

        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = str(candidate or "").strip()
            if not normalized or normalized in seen:
                continue
            deduped.append(normalized)
            seen.add(normalized)
        return deduped

    def apply_glossary_postprocess(self, text: str, target_lang: str) -> str:
        if target_lang == "ko":
            return self._normalize_text(text)

        target_col = self.GLOSSARY_COL_MAP[target_lang]
        out = str(text or "")
        rows = sorted(
            self.glossary_df.to_dict("records"),
            key=lambda row: len(str(row.get(self.SOURCE_TERM_COL, ""))),
            reverse=True,
        )
        for row in rows:
            source_term = str(row.get(self.SOURCE_TERM_COL, "")).strip()
            translated_term = str(row.get(target_col, "")).strip()
            if not source_term or not translated_term:
                continue
            out = out.replace(source_term, translated_term)
        return self._normalize_text(out)

    def translate_text(self, text: str, policy_text: str, target_lang: str) -> Dict[str, str]:
        text = self._normalize_text(text)
        policy_text = clean_policy_text(policy_text)
        target_lang = str(target_lang or "ko").strip().lower()

        if not text:
            raise ValueError("text is empty.")
        if target_lang not in self.LANG_MAP:
            raise ValueError(f"Unsupported language: {target_lang}")

        if target_lang == "ko":
            return {
                "language": "ko",
                "translated_text": text,
                "translation_source": "original",
                "is_fallback": False,
            }

        protected_text, replacements = protect_special_tokens(text)
        glossary_str = self._extract_relevant_glossary(text, policy_text, target_lang)
        schema = self.prompt_builder.get_translation_schema()
        messages = self.prompt_builder.build_translation_messages(
            text=protected_text,
            target_lang=target_lang,
            glossary_text=glossary_str,
            policy_context=policy_text,
        )
        last_error: Exception | None = None
        data: Dict[str, str] | None = None
        for candidate_model in self._candidate_models(target_lang):
            try:
                data = self._call_model_json_for_model(candidate_model, messages, schema)
                break
            except Exception as exc:
                last_error = exc
                continue

        if data is None:
            raise RuntimeError(f"Translation failed for all candidate models: {last_error}")

        translated_text = str(data.get("translated_text", "")).strip()
        if not translated_text:
            raise RuntimeError("Translated text is empty.")

        translated_text = restore_special_tokens(translated_text, replacements)
        translated_text = self.apply_glossary_postprocess(translated_text, target_lang)
        translated_text = self._localize_money_units(translated_text, target_lang)

        if count_preserve_tokens(translated_text) > 0:
            raise RuntimeError("Translation still contains unresolved preserve tokens.")

        return {
            "language": target_lang,
            "translated_text": translated_text,
            "translation_source": "qwen",
            "is_fallback": False,
        }
