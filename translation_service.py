import json
import os
import urllib.error
import urllib.request
from typing import Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv

from prompt_builder import PromptBuilder


class PolicyTranslationService:
    REQUIRED_COLUMNS = ["행정 용어", "영어", "베트남어", "중국어", "일본어"]

    LANG_MAP = {
        "ko": "한국어",
        "en": "영어",
        "vi": "베트남어",
        "zh": "중국어",
        "ja": "일본어",
    }

    GLOSSARY_COL_MAP = {
        "en": "영어",
        "vi": "베트남어",
        "zh": "중국어",
        "ja": "일본어",
    }

    def __init__(
        self,
        csv_path: str = "benepick_dict.csv",
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        prompt_path: Optional[str] = None,
    ) -> None:
        load_dotenv()

        self.model_name = model_name or os.getenv("QWEN_MODEL", "qwen3:4b")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.timeout = float(timeout or os.getenv("OLLAMA_TIMEOUT", "300"))
        self.prompt_path = prompt_path or os.getenv("TRANSLATION_PROMPT_PATH", "prompts/prompt_translation.txt")

        self.glossary_df = self._load_glossary(csv_path)
        self.prompt_builder = self._build_prompt_builder()

        print(f"🌐 번역 모델({self.model_name}) 준비 완료")

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
            raise ValueError(f"CSV에 필요한 컬럼이 없습니다: {missing}")

        df = df[self.REQUIRED_COLUMNS].fillna("")
        for col in self.REQUIRED_COLUMNS:
            df[col] = df[col].astype(str).str.strip()

        return df[df["행정 용어"] != ""].reset_index(drop=True)

    def _extract_relevant_glossary(self, text: str, target_lang: str) -> str:
        if target_lang == "ko":
            return ""

        target_col = self.GLOSSARY_COL_MAP[target_lang]
        matches = []

        for _, row in self.glossary_df.iterrows():
            term = row["행정 용어"]
            translated = row[target_col]
            if term and translated and term in text:
                matches.append(f"- {term} -> {translated}")

        return "\n".join(matches)

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
            raise RuntimeError(f"Ollama HTTP 오류: {exc.code} / {body}") from exc
        except Exception as exc:
            raise RuntimeError(f"Ollama 호출 실패: {exc}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Ollama 응답 파싱 실패: {raw[:500]}") from exc

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
            raise RuntimeError("모델 응답이 비어 있습니다.")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"모델 content JSON 파싱 실패: {content}") from exc

        return parsed

    def translate_text(self, text: str, policy_text: str, target_lang: str) -> Dict[str, str]:
        text = str(text or "").strip()
        policy_text = str(policy_text or "")
        target_lang = str(target_lang or "ko").strip().lower()

        if not text:
            raise ValueError("번역할 text가 비어 있습니다.")
        if target_lang not in self.LANG_MAP:
            raise ValueError(f"지원하지 않는 언어입니다: {target_lang}")

        if target_lang == "ko":
            return {
                "language": "ko",
                "translated_text": text,
                "translation_source": "original",
            }

        glossary_str = self._extract_relevant_glossary(policy_text, target_lang)
        schema = self.prompt_builder.get_translation_schema()
        messages = self.prompt_builder.build_translation_messages(
            text=text,
            target_lang=target_lang,
            glossary_text=glossary_str,
        )

        data = self._call_model_json(messages, schema)
        translated_text = str(data.get("translated_text", "")).strip()

        if not translated_text:
            raise RuntimeError("번역 결과가 비어 있습니다.")

        return {
            "language": target_lang,
            "translated_text": translated_text,
            "translation_source": "qwen",
        }
