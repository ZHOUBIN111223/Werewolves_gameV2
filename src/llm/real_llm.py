"""Production LLM service implementation backed by LiteLLM."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict

import litellm
from litellm import completion

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from config import APIConfig


class RealLLM:
    """Single production LLM implementation used across the project."""

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.api_url = api_url or APIConfig.CUSTOM_LLM_ENDPOINT
        self.api_key = api_key or APIConfig.CUSTOM_LLM_API_KEY
        self.model = model or APIConfig.DEFAULT_MODEL
        self.timeout = timeout or APIConfig.API_TIMEOUT
        self.max_retries = max_retries or APIConfig.MAX_RETRIES

        litellm.api_base = self.api_url
        litellm.api_key = self.api_key

    def invoke(self, prompt: Dict[str, Any]) -> Dict[str, Any]:
        """Call the configured model and return a validated structured response."""

        prompt_type = str(prompt.get("prompt_type", "")).strip()
        messages = self._build_messages(prompt, prompt_type)

        attempt = 0
        last_error: Exception | None = None
        while attempt < self.max_retries:
            try:
                response = completion(
                    model=self.model,
                    messages=messages,
                    temperature=0.7,
                    timeout=self.timeout,
                )
                content = response.choices[0].message.content
                result = self._parse_json_response(content)
                return self._validate_response_format(result, prompt_type)
            except Exception as exc:
                print(f"LLM call failed (attempt {attempt + 1}/{self.max_retries}): {exc}")
                last_error = exc
                attempt += 1

        print(f"Primary LLM call failed, trying backup provider: {last_error}")
        return self._try_backup_api(prompt, prompt_type)

    def _try_backup_api(self, prompt: Dict[str, Any], prompt_type: str) -> Dict[str, Any]:
        """Fallback to a Bailian-compatible endpoint if the primary call fails."""

        bailian_api_key = os.getenv("BAILIAN_API_KEY", APIConfig.BAILIAN_API_KEY).strip()
        if not bailian_api_key:
            print("Backup Bailian API key is not configured.")
            return self._get_default_response(prompt_type)

        try:
            response = completion(
                model=f"openai/{os.getenv('BAILIAN_DEFAULT_MODEL', APIConfig.BAILIAN_DEFAULT_MODEL)}",
                api_key=bailian_api_key,
                api_base=os.getenv("BAILIAN_API_BASE", APIConfig.BAILIAN_ENDPOINT),
                messages=self._build_messages(prompt, prompt_type),
                temperature=0.7,
                timeout=self.timeout,
            )
            content = response.choices[0].message.content
            result = self._parse_json_response(content)
            print("Backup API call succeeded.")
            return self._validate_response_format(result, prompt_type)
        except Exception as exc:
            print(f"Backup API call failed: {exc}")
            return self._get_default_response(prompt_type)

    def _build_messages(self, prompt: Dict[str, Any], prompt_type: str) -> list[Dict[str, str]]:
        """Build chat messages for action and reflection prompts."""

        prompt_payload = json.dumps(prompt, ensure_ascii=False, indent=2, default=str)

        if prompt_type == "action":
            system_content = (
                "You are an AI player in a Werewolf game. "
                "Return exactly one JSON object and nothing else. "
                "The JSON must contain: action_type, target, reasoning_summary, public_speech. "
                "Allowed action_type values are speak, vote, inspect, kill, protect, poison, heal, skip, hunt. "
                "Respect request_kind, available_actions, available_targets, phase, role_instruction, "
                "phase_instructions, and specific_guidance from the provided context. "
                "If action_type is speak, public_speech must be a short Chinese sentence. "
                "For non-speak actions, public_speech may be an empty string."
            )
            user_content = prompt_payload
        elif prompt_type == "reflection":
            system_content = (
                "You are reviewing a finished Werewolf game. "
                "Return exactly one JSON object with the keys: "
                "mistakes, correct_reads, useful_signals, bad_patterns, strategy_rules, confidence. "
                "confidence must be a number between 0 and 1."
            )
            user_content = prompt_payload
        else:
            system_content = "Return a single JSON object based on the provided context."
            user_content = prompt_payload

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

    def _parse_json_response(self, content: str) -> Dict[str, Any]:
        """Parse the model output into a JSON object."""

        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                return json.loads(match.group())
            raise ValueError(f"Unable to parse response as JSON: {content}")

    def _validate_response_format(self, result: Dict[str, Any], prompt_type: str) -> Dict[str, Any]:
        """Normalize missing fields so downstream code receives a stable schema."""

        if prompt_type == "action":
            expected_fields = ["action_type", "target", "reasoning_summary", "public_speech"]
            for field in expected_fields:
                if field not in result:
                    result[field] = ""

            if result.get("target") is None:
                result["target"] = ""
            if result.get("public_speech") is None:
                result["public_speech"] = ""

            action_type = str(result.get("action_type", "")).lower()
            if action_type == "speak" and not str(result.get("public_speech", "")).strip():
                result["public_speech"] = "我先听大家的发言，再给出判断。"

        elif prompt_type == "reflection":
            expected_fields = [
                "mistakes",
                "correct_reads",
                "useful_signals",
                "bad_patterns",
                "strategy_rules",
                "confidence",
            ]
            for field in expected_fields:
                if field not in result:
                    result[field] = 0.5 if field == "confidence" else []

        return result

    def _get_default_response(self, prompt_type: str) -> Dict[str, Any]:
        """Return a safe fallback when every API call fails."""

        if prompt_type == "action":
            return {
                "action_type": "speak",
                "target": "",
                "reasoning_summary": "LLM service unavailable, using fallback action.",
                "public_speech": "我先听大家的发言，再给出判断。",
            }

        if prompt_type == "reflection":
            return {
                "mistakes": ["LLM service unavailable"],
                "correct_reads": [],
                "useful_signals": [],
                "bad_patterns": ["Reflection was generated from fallback logic only"],
                "strategy_rules": ["Retry reflection after the model service is restored"],
                "confidence": 0.5,
            }

        return {"error": "unknown prompt type"}
