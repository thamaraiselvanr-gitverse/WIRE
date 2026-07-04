"""
LLM Client — Thin Wrapper Around the Google Gen AI SDK (Gemini).

Provides structured, JSON-mode LLM calls for the semantic layer.
All calls go through LLMGuard for input preparation and output
validation — this module handles only the transport layer.

Uses the ``google-genai`` SDK (``from google import genai``), the supported
successor to the deprecated ``google-generativeai`` package.
"""

import json
import os
from typing import Any, Optional

import structlog
from google import genai
from google.genai import types

logger = structlog.get_logger(__name__)

# Default model — can be overridden via environment variable
_DEFAULT_MODEL = "gemini-2.0-flash"


class LLMClient:
    """
    Thin wrapper around the Google Gen AI SDK for structured output.

    Configured via GEMINI_API_KEY environment variable. If no key is
    set, all calls return None (graceful degradation, not a crash).
    """

    def __init__(self, model_name: Optional[str] = None) -> None:
        self._model_name = model_name or os.environ.get(
            "WIRE_LLM_MODEL", _DEFAULT_MODEL
        )
        self._api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get(
            "GOOGLE_API_KEY"
        )
        self._client: Optional[genai.Client] = None

        if self._api_key:
            try:
                self._client = genai.Client(api_key=self._api_key)
                logger.info(
                    "llm_client_initialized",
                    model=self._model_name,
                )
            except Exception as e:
                logger.error("llm_client_init_failed", error=str(e))
                self._client = None
        else:
            logger.warning(
                "llm_client_no_api_key",
                hint="Set GEMINI_API_KEY or GOOGLE_API_KEY to enable LLM features",
            )

    @property
    def is_available(self) -> bool:
        """Whether the LLM client is configured and ready."""
        return self._client is not None

    def generate_json(
        self,
        system_instruction: str,
        user_content: str,
        temperature: float = 0.1,
    ) -> Optional[dict[str, Any]]:
        """
        Generate a structured JSON response from the LLM.

        Uses Gemini's JSON response mode for constrained output.
        Returns None if the LLM is unavailable or the response is
        not valid JSON (fail-closed).
        """
        if not self.is_available or self._client is None:
            return None

        try:
            response = self._client.models.generate_content(
                model=self._model_name,
                contents=user_content,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=temperature,
                ),
            )

            if not response.text:
                logger.warning("llm_client_empty_response")
                return None

            result: Any = json.loads(response.text)
            if not isinstance(result, dict):
                logger.warning(
                    "llm_client_non_dict_response", type=type(result).__name__
                )
                return None

            logger.info("llm_client_response_received", keys=list(result.keys()))
            return result

        except json.JSONDecodeError as e:
            logger.warning("llm_client_json_parse_error", error=str(e))
            return None
        except Exception as e:
            logger.error("llm_client_call_error", error=str(e))
            return None
