"""Production LLM service implementation backed by LiteLLM."""

from __future__ import annotations

import json
import os
import re
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import litellm
from litellm import completion

# 允许将此模块作为脚本/独立模块运行时也能正确导入项目根目录下的 `config.py`。
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from config import APIConfig, AppConfig


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
        """创建真实 LLM 调用器，并把配置注入到 LiteLLM。

        参数若为空，将回退到 `config.APIConfig` 与环境变量中的默认值。
        """
        self.api_url = api_url or APIConfig.CUSTOM_LLM_ENDPOINT
        self.api_key = api_key or APIConfig.CUSTOM_LLM_API_KEY
        self.model = model or APIConfig.DEFAULT_MODEL
        self.timeout = timeout or APIConfig.API_TIMEOUT
        self.max_retries = max_retries or APIConfig.MAX_RETRIES
        self.trace_root = Path(AppConfig.LOG_PATH) / "llm_traces"
        self.trace_root.mkdir(parents=True, exist_ok=True)

        # LiteLLM 全局配置：后续 completion() 会读取这些默认值。
        litellm.api_base = self.api_url
        litellm.api_key = self.api_key

    def _resolve_completion_model(self, model_name: str | None = None) -> str:
        """Normalize provider-specific model ids for LiteLLM."""
        resolved_model = str(model_name or self.model).strip()
        if not resolved_model:
            return resolved_model
        if "/" in resolved_model:
            return resolved_model
        if "dashscope.aliyuncs.com" in str(self.api_url):
            return f"openai/{resolved_model}"
        return resolved_model

    def _safe_trace_slug(self, value: Any, fallback: str) -> str:
        text = str(value or "").strip()
        if not text:
            return fallback
        text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
        text = text.strip("._-")
        return text[:80] or fallback

    def _write_trace_json(self, trace_dir: Path, filename: str, payload: Any) -> None:
        (trace_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def _write_trace_text(self, trace_dir: Path, filename: str, content: Any) -> None:
        if isinstance(content, (dict, list)):
            text = json.dumps(content, ensure_ascii=False, indent=2, default=str)
        elif content is None:
            text = ""
        else:
            text = str(content)
        (trace_dir / filename).write_text(text, encoding="utf-8")

    def _start_trace(
        self,
        prompt: dict[str, Any],
        prompt_type: str,
        messages: list[dict[str, str]],
        *,
        provider: str,
        attempt: int,
        model_name: str,
    ) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        game_id = self._safe_trace_slug(prompt.get("game_id"), "no_game")
        request_kind = self._safe_trace_slug(prompt.get("request_kind"), "no_request")
        role = self._safe_trace_slug(prompt.get("role"), "no_role")
        subphase = self._safe_trace_slug(
            prompt.get("current_subphase") or prompt.get("subphase"),
            "no_subphase",
        )
        trace_id = f"{timestamp}_{provider}_a{attempt}_{uuid.uuid4().hex[:8]}"
        trace_dir = self.trace_root / game_id / f"{request_kind}_{role}_{subphase}_{trace_id}"
        trace_dir.mkdir(parents=True, exist_ok=True)
        self._write_trace_json(
            trace_dir,
            "meta.json",
            {
                "timestamp_utc": timestamp,
                "provider": provider,
                "attempt": attempt,
                "prompt_type": prompt_type,
                "game_id": prompt.get("game_id", ""),
                "role": prompt.get("role", ""),
                "phase": prompt.get("phase", ""),
                "request_kind": prompt.get("request_kind", ""),
                "current_subphase": prompt.get("current_subphase", ""),
                "model": model_name,
                "api_base": self.api_url if provider == "primary" else os.getenv("BAILIAN_API_BASE", APIConfig.BAILIAN_ENDPOINT),
            },
        )
        self._write_trace_json(trace_dir, "prompt.json", prompt)
        self._write_trace_json(trace_dir, "messages.json", messages)
        return trace_dir

    def _write_trace_success(
        self,
        trace_dir: Path,
        *,
        raw_content: Any,
        parsed_result: dict[str, Any],
        validated_result: dict[str, Any],
    ) -> None:
        self._write_trace_text(trace_dir, "raw_response.txt", raw_content)
        self._write_trace_json(trace_dir, "parsed_response.json", parsed_result)
        self._write_trace_json(trace_dir, "validated_response.json", validated_result)
        self._write_trace_json(
            trace_dir,
            "status.json",
            {
                "status": "success",
                "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _write_trace_error(
        self,
        trace_dir: Path,
        *,
        raw_content: Any,
        exc: Exception,
    ) -> None:
        if raw_content is not None:
            self._write_trace_text(trace_dir, "raw_response.txt", raw_content)
        self._write_trace_json(
            trace_dir,
            "error.json",
            {
                "status": "error",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "traceback": traceback.format_exc(),
                "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _request_options_for_prompt(self, prompt_type: str) -> dict[str, Any]:
        """Use stricter limits for post-game reflection so one slow request cannot block the run."""
        options = {
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "temperature": 0.7,
            "allow_backup": True,
        }
        if prompt_type == "reflection":
            options.update(
                {
                    "timeout": max(1, min(self.timeout, APIConfig.REFLECTION_API_TIMEOUT)),
                    "max_retries": max(1, APIConfig.REFLECTION_MAX_RETRIES),
                    "temperature": 0.3,
                    "allow_backup": False,
                }
            )
        return options

    def invoke(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """Call the configured model and return a validated structured response."""

        prompt_type = str(prompt.get("prompt_type", "")).strip()
        messages = self._build_messages(prompt, prompt_type)
        request_options = self._request_options_for_prompt(prompt_type)
        request_timeout = int(request_options["timeout"])
        request_retries = int(request_options["max_retries"])
        request_temperature = float(request_options["temperature"])
        allow_backup = bool(request_options["allow_backup"])

        attempt = 0
        last_error: Exception | None = None
        while attempt < request_retries:
            model_name = self._resolve_completion_model()
            trace_dir = self._start_trace(
                prompt,
                prompt_type,
                messages,
                provider="primary",
                attempt=attempt + 1,
                model_name=model_name,
            )
            raw_content = None
            try:
                response = completion(
                    model=model_name,
                    messages=messages,
                    temperature=request_temperature,
                    timeout=request_timeout,
                )
                raw_content = response.choices[0].message.content
                result = self._parse_json_response(raw_content)
                validated_result = self._validate_response_format(result, prompt_type)
                self._write_trace_success(
                    trace_dir,
                    raw_content=raw_content,
                    parsed_result=result,
                    validated_result=validated_result,
                )
                return validated_result
            except Exception as exc:
                self._write_trace_error(trace_dir, raw_content=raw_content, exc=exc)
                print(f"LLM call failed (attempt {attempt + 1}/{request_retries}): {exc}")
                last_error = exc
                attempt += 1

        if allow_backup:
            print(f"Primary LLM call failed, trying backup provider: {last_error}")
            return self._try_backup_api(
                prompt,
                prompt_type,
                timeout=request_timeout,
                temperature=request_temperature,
            )

        print(f"LLM call failed without backup fallback: {last_error}")
        return self._get_default_response(prompt_type)

    def _try_backup_api(
        self,
        prompt: dict[str, Any],
        prompt_type: str,
        *,
        timeout: int,
        temperature: float,
    ) -> dict[str, Any]:
        """Fallback to a Bailian-compatible endpoint if the primary call fails."""

        bailian_api_key = os.getenv("BAILIAN_API_KEY", APIConfig.BAILIAN_API_KEY).strip()
        backup_model = self._resolve_completion_model(
            os.getenv("BAILIAN_DEFAULT_MODEL", APIConfig.BAILIAN_DEFAULT_MODEL)
        )
        messages = self._build_messages(prompt, prompt_type)
        trace_dir = self._start_trace(
            prompt,
            prompt_type,
            messages,
            provider="backup",
            attempt=1,
            model_name=backup_model,
        )
        if not bailian_api_key:
            print("Backup Bailian API key is not configured.")
            exc = RuntimeError("Backup Bailian API key is not configured.")
            self._write_trace_error(trace_dir, raw_content=None, exc=exc)
            default_response = self._get_default_response(prompt_type)
            self._write_trace_json(trace_dir, "default_response.json", default_response)
            return default_response

        raw_content = None
        try:
            response = completion(
                model=backup_model,
                api_key=bailian_api_key,
                api_base=os.getenv("BAILIAN_API_BASE", APIConfig.BAILIAN_ENDPOINT),
                messages=messages,
                temperature=temperature,
                timeout=timeout,
            )
            raw_content = response.choices[0].message.content
            result = self._parse_json_response(raw_content)
            print("Backup API call succeeded.")
            validated_result = self._validate_response_format(result, prompt_type)
            self._write_trace_success(
                trace_dir,
                raw_content=raw_content,
                parsed_result=result,
                validated_result=validated_result,
            )
            return validated_result
        except Exception as exc:
            self._write_trace_error(trace_dir, raw_content=raw_content, exc=exc)
            print(f"Backup API call failed: {exc}")
            default_response = self._get_default_response(prompt_type)
            self._write_trace_json(trace_dir, "default_response.json", default_response)
            return default_response

    def _build_messages(self, prompt: dict[str, Any], prompt_type: str) -> list[dict[str, str]]:
        """Build chat messages for action and reflection prompts."""
        prompt_payload = json.dumps(prompt, ensure_ascii=False, indent=2, default=str)

        if prompt_type == "action":
            system_content = (
                "You are an AI player in a Werewolf game. "
                "Return exactly one JSON object and nothing else. "
                "The JSON must contain action_type, target, reasoning_summary, and public_speech. "
                "Allowed action_type values are speak, vote, inspect, kill, protect, poison, heal, skip, and hunt. "
                "You are handling exactly one explicit request. "
                "The hard_constraints field has the highest priority and must be obeyed exactly. "
                "Also obey request_kind, available_actions, available_targets, alive_players, role_instruction, phase_instructions, speech_rules, specific_guidance, and response_checklist. "
                "Before output, check must_action_type first, then whether target must be empty or selected from a legal list, then whether public_speech must be empty or non-empty. "
                "If any field conflicts with hard_constraints, fix it before output. "
                "For speak requests, action_type must be speak, target must be an empty string, and public_speech must be non-empty Chinese. "
                "For vote requests, action_type must be vote, target must come from available_targets or vote_candidates, and public_speech must be an empty string. "
                "When speaking, you may reference dead players, night deaths, past speeches, vote records, or badge flow to review the game state. "
                "But current suspicion targets, pressure targets, and vote targets must remain legal living players. "
                "If you suspect someone, explain it naturally with game evidence such as timing, vote records, speech inconsistencies, claimed identities, or night results instead of formulaic filler. "
                "Do not output explanations, markdown, code fences, or anything outside the JSON object."
            )
            user_content = prompt_payload
        elif prompt_type == "reflection":
            system_content = (
                "你正在复盘一局已经结束的狼人杀游戏。"
                "只能输出一个 JSON 对象。"
                "JSON 必须包含 mistakes、correct_reads、useful_signals、bad_patterns、strategy_rules、confidence。"
                "confidence 必须是 0 到 1 之间的数字。"
            )
            user_content = prompt_payload
        else:
            system_content = "请根据提供的上下文只输出一个 JSON 对象。"
            user_content = prompt_payload

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

    def _parse_json_response(self, content: str) -> dict[str, Any]:
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

    def _validate_response_format(
        self, result: dict[str, Any], prompt_type: str
    ) -> dict[str, Any]:
        """Normalize missing fields so downstream code receives a stable schema."""

        if prompt_type == "action":
            if "target" in result and result.get("target") is None:
                result["target"] = ""
            if "public_speech" in result and result.get("public_speech") is None:
                result["public_speech"] = ""

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

    def _get_default_response(self, prompt_type: str) -> dict[str, Any]:
        """Return a safe fallback when every API call fails."""

        if prompt_type == "action":
            return {
                "action_type": "",
                "target": "",
                "reasoning_summary": "LLM service unavailable.",
                "public_speech": "",
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
