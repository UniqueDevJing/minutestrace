import json
import time
from typing import Any

import httpx
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AiCallLog, AiModelConfig, PromptTemplate
from .schemas import MinutesContent, SpeakerSuggestions


class QwenClient:
    def __init__(self, db: Session, meeting_id: int | None = None):
        self.db = db
        self.meeting_id = meeting_id
        self.settings = get_settings()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.llm_api_key)

    def model_settings(self, purpose: str) -> tuple[str, str]:
        config = self.db.scalar(select(AiModelConfig).where(AiModelConfig.purpose == purpose, AiModelConfig.enabled.is_(True)))
        if config:
            return config.model, config.base_url
        disabled = self.db.scalar(select(AiModelConfig).where(AiModelConfig.purpose == purpose, AiModelConfig.enabled.is_(False)))
        if disabled:
            return "", ""
        return self.settings.llm_model, self.settings.llm_base_url

    def prompt(self, purpose: str, fallback: str) -> str:
        template = self.db.scalar(
            select(PromptTemplate)
            .where(PromptTemplate.purpose == purpose, PromptTemplate.enabled.is_(True))
            .order_by(PromptTemplate.version.desc())
            .limit(1)
        )
        return template.template if template else fallback

    def json_call(
        self,
        purpose: str,
        system: str,
        user: str,
        response_schema: type[BaseModel] | None = None,
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        started = time.perf_counter()
        success = False
        error = ""
        prompt_tokens = completion_tokens = 0
        model, base_url = self.model_settings(purpose)
        if not model or not base_url:
            return None
        try:
            response_format: dict[str, Any] = {"type": "json_object"}
            if response_schema is not None:
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_schema.__name__.lower(),
                        "strict": True,
                        "schema": response_schema.model_json_schema(),
                    },
                }
            response = httpx.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                json={
                    "model": model,
                    "temperature": 0,
                    "response_format": response_format,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                },
                timeout=90,
            )
            response.raise_for_status()
            body = response.json()
            usage = body.get("usage") or {}
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            content = body["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0]
            result = json.loads(content)
            if response_schema is not None:
                result = response_schema.model_validate(result).model_dump(mode="json")
            success = True
            return result
        except Exception as exc:  # provider failures are logged and deterministic fallback continues
            error = str(exc)[:500]
            return None
        finally:
            self.db.add(
                AiCallLog(
                    meeting_id=self.meeting_id,
                    purpose=purpose,
                    model=model,
                    success=success,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    error=error,
                )
            )
            self.db.commit()

    def generate_minutes(self, transcript: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
        schema = {
            "summary": "string",
            "topics": [{"title": "string", "summary": "string", "evidence_segment_ids": [1]}],
            "decisions": [{"text": "string", "evidence_segment_ids": [1], "needs_confirmation": False}],
            "action_items": [
                {"text": "string", "owner": "string or 待确认", "due": "string or 待确认", "evidence_segment_ids": [1]}
            ],
            "open_questions": [{"text": "string", "evidence_segment_ids": [1]}],
            "risks": [{"text": "string", "evidence_segment_ids": [1]}],
        }
        return self.json_call(
            "minutes_generation",
            self.prompt("minutes_generation", "你是会议纪要提取器。只记录转写中出现的事实。负责人或日期不明确时写待确认。每一项必须引用真实 segment id。只输出 JSON。"),
            json.dumps({"meeting_title": title, "output_schema": schema, "transcript": transcript}, ensure_ascii=False),
            response_schema=MinutesContent,
        )

    def review_minutes(self, minutes: dict[str, Any], transcript: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = self.json_call(
            "minutes_review",
            self.prompt("minutes_review", "对照转写审查纪要。分别检查完整性、可落实性和无来源事实。只输出 {issues:[{field,index,severity,message}]} JSON。"),
            json.dumps({"minutes": minutes, "transcript": transcript}, ensure_ascii=False),
        )
        return (result or {}).get("issues", []) if isinstance(result, dict) else []

    def suggest_speakers(self, participants: list[str], transcript: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = self.json_call(
            "speaker_matching",
            self.prompt("speaker_matching", "根据参会人名单和转写片段，建议 speaker_label 对应的人。只能从参会人名单中选择，无法判断时使用待确认。只输出 JSON。"),
            json.dumps({"participants": participants, "transcript": transcript[:120]}, ensure_ascii=False),
            response_schema=SpeakerSuggestions,
        )
        return (result or {}).get("suggestions", []) if isinstance(result, dict) else []

    def revise_minutes(self, minutes: dict[str, Any], issues: list[dict[str, Any]], transcript: list[dict[str, Any]]) -> dict[str, Any] | None:
        return self.json_call(
            "minutes_revision",
            self.prompt("minutes_revision", "按问题清单修订纪要。不得新增转写中没有的事实，必须保留 evidence_segment_ids；缺失负责人或日期写待确认。输出完整纪要 JSON。"),
            json.dumps({"minutes": minutes, "issues": issues, "transcript": transcript}, ensure_ascii=False),
        )
