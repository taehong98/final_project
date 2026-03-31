import json
import os
import re
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from dotenv import load_dotenv


class PolicySummaryService:
    DEFAULT_SUMMARY_PROMPT = """너는 대한민국 복지 정책 요약 도우미다.

[목표]
- 복지 정책 원문을 일반 사용자도 이해하기 쉽게 3~5문장으로 요약한다.

[스타일]
- 쉬운 한국어로 쓴다.
- 핵심 정보만 남긴다.
- 불필요하게 길게 쓰지 않는다.
- 추측하지 않는다.

[핵심 규칙]
1. 정책 원문에 있는 정보만 사용한다.
2. 정책 원문에 없는 기관, 금액, 기간, 자격, 서류를 추가하지 않는다.
3. 반드시 한국어 JSON만 출력한다.
4. 출력 키는 반드시 summary만 사용한다.
5. summary는 3~5문장으로 작성한다.
"""

    def __init__(
        self,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        prompt_path: Optional[str] = None,
    ) -> None:
        load_dotenv()

        self.model_name = model_name or os.getenv("QWEN_MODEL", "qwen3:4b")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.timeout = float(timeout or os.getenv("OLLAMA_TIMEOUT", "300"))
        self.prompt_path = prompt_path or os.getenv("SUMMARY_PROMPT_PATH", "prompts/prompt_summary.txt")
        self.summary_prompt_base = self._load_summary_prompt_base()

        print(f"📝 요약 모델({self.model_name}) 준비 완료")

    def _load_summary_prompt_base(self) -> str:
        path = str(self.prompt_path or "").strip()
        if not path:
            return self.DEFAULT_SUMMARY_PROMPT

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            return content or self.DEFAULT_SUMMARY_PROMPT
        except FileNotFoundError:
            print(f"⚠️ 요약 프롬프트 파일을 찾지 못해 기본 프롬프트를 사용합니다: {path}")
            return self.DEFAULT_SUMMARY_PROMPT
        except Exception as exc:
            print(f"⚠️ 요약 프롬프트 파일 로드 실패로 기본 프롬프트를 사용합니다: {exc}")
            return self.DEFAULT_SUMMARY_PROMPT

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
            raise RuntimeError(f"모델 응답이 비어 있습니다: {json.dumps(outer, ensure_ascii=False)[:500]}")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"모델 content JSON 파싱 실패: {content}") from exc

        if not isinstance(parsed, dict):
            raise RuntimeError(f"모델 JSON 응답 형식이 잘못되었습니다: {parsed}")

        return parsed

    def _looks_like_korean(self, text: str) -> bool:
        return bool(re.search(r"[가-힣]", str(text)))

    def summarize_policy(self, policy_text: str) -> Dict[str, str]:
        policy_text = str(policy_text or "").strip()
        if not policy_text:
            raise ValueError("policy_text가 비어 있습니다.")

        schema = {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
            },
            "required": ["summary"],
            "additionalProperties": False,
        }

        prompt = f"""
{self.summary_prompt_base}

[정책 원문]
{policy_text}
""".strip()

        messages = [
            {
                "role": "system",
                "content": "Return only valid JSON matching the schema. Use Korean only. Key must be summary.",
            },
            {"role": "user", "content": prompt},
        ]

        data = self._call_model_json(messages, schema)
        summary = str(data.get("summary", "")).strip()

        if not summary:
            raise RuntimeError("요약 결과가 비어 있습니다.")
        if not self._looks_like_korean(summary):
            raise RuntimeError(f"요약 결과가 한국어가 아닙니다: {summary}")

        return {
            "language": "ko",
            "summary": summary,
            "summary_source": "qwen",
        }


if __name__ == "__main__":
    service = PolicySummaryService()

    sample_policy = """
청년월세지원은 만 19세~34세 이하이면서 소득 60% 이하인 무주택 청년에게 월세 일부를 지원합니다.
신청은 지정된 기간 내 온라인으로 가능하며, 세부 자격 요건은 공고문을 확인해야 합니다.
""".strip()

    result = service.summarize_policy(sample_policy)
    print(json.dumps(result, ensure_ascii=False, indent=4))