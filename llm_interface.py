# llm_interface.py

from __future__ import annotations

import os
import time
import json
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

class LLMGenerationError(RuntimeError):
    """A provider call failed.

    Providers used to swallow this and return the string ``Error generating
    response: ...``. That string then flowed onward as if it were model output:
    it was written to ``final_report.md`` as the report, and a failed branch
    summary silently poisoned the evidence pool. Failures now propagate so a
    caller can decide, per call site, whether to degrade or abort.
    """


DEFAULT_PROVIDER_MODELS = {
    "ollama": "gemma2:2b",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    "litellm": "gpt-4o-mini",
}


def default_model_for_provider(provider: str, rag_model: str = "gemma") -> str:
    """
    Resolve provider defaults with environment overrides.

    Environment variables intentionally make model upgrades operational instead
    of source-code edits:
      - NANOSAGE_OLLAMA_MODEL
      - NANOSAGE_OPENAI_MODEL
      - NANOSAGE_ANTHROPIC_MODEL
      - NANOSAGE_LITELLM_MODEL
    """
    provider_key = (provider or "ollama").lower()
    env_name = f"NANOSAGE_{provider_key.upper()}_MODEL"
    if os.getenv(env_name):
        return os.environ[env_name]
    if provider_key == "litellm" and os.getenv("LITELLM_MODEL"):
        return os.environ["LITELLM_MODEL"]
    return DEFAULT_PROVIDER_MODELS.get(provider_key, DEFAULT_PROVIDER_MODELS["ollama"])


def _summary_prompt(
    text: str,
    question: Optional[str] = None,
    *,
    part: Optional[tuple] = None,
    combining: bool = False,
) -> str:
    """Build a summarization prompt, question-directed when a question is given."""
    scope = ""
    if part:
        scope = f" This is part {part[0]} of {part[1]}; summarize only this part."
    if combining:
        scope = " These are partial summaries of one evidence set; combine them."
    if not question:
        return f"Please summarize the following text succinctly.{scope}\n\n{text}"
    return (
        f"Research question: {question}\n\n"
        "Summarize the evidence below as an answer to that question. Lead with what the "
        "evidence establishes about it, keep concrete figures, model names and conditions, "
        "and say explicitly if the evidence does not address the question. Omit material "
        f"that is irrelevant to it.{scope}\n\n{text}"
    )


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    def generate(self, prompt: str, system_message: Optional[str] = None, **kwargs) -> str:
        """Generate a response from the LLM."""
        pass
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """Return the name of the provider."""
        pass

class OllamaProvider(LLMProvider):
    """Ollama provider implementation."""
    
    def __init__(self, model: str = "gemma2:2b", **kwargs):
        self.model = model
        self.kwargs = kwargs
        try:
            from ollama import chat, ChatResponse
            self.chat = chat
            self.ChatResponse = ChatResponse
        except ImportError:
            raise ImportError("Ollama not available. Install with: pip install ollama")
    
    def generate(self, prompt: str, system_message: Optional[str] = None, **kwargs) -> str:
        """Generate response using Ollama."""
        messages = []
        
        if system_message:
            messages.append({"role": "system", "content": system_message})
        
        messages.append({"role": "user", "content": prompt})
        
        try:
            response = self.chat(
                model=self.model,
                messages=messages,
                **{**self.kwargs, **kwargs}
            )
            return response.message.content
        except Exception as e:
            print(f"[ERROR] Ollama generation failed: {e}")
            raise LLMGenerationError(f"ollama generation failed: {e}") from e
    
    def get_provider_name(self) -> str:
        return f"ollama:{self.model}"

class OpenAIProvider(LLMProvider):
    """OpenAI provider implementation."""
    
    def __init__(self, model: str = DEFAULT_PROVIDER_MODELS["openai"], api_key: Optional[str] = None,
                 base_url: Optional[str] = None, **kwargs):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.kwargs = {
            key: value
            for key, value in kwargs.items()
            if key not in {"timeout", "max_retries"}
        }
        
        if not self.api_key:
            raise ValueError("OpenAI API key not provided. Set OPENAI_API_KEY environment variable or pass api_key parameter.")
        
        try:
            import openai
            client_kwargs = {"api_key": self.api_key}
            if base_url:
                client_kwargs["base_url"] = base_url
            if kwargs.get("timeout") is not None:
                client_kwargs["timeout"] = kwargs["timeout"]
            if kwargs.get("max_retries") is not None:
                client_kwargs["max_retries"] = kwargs["max_retries"]
            self.client = openai.OpenAI(**client_kwargs)
        except ImportError:
            raise ImportError("OpenAI not available. Install with: pip install openai")
    
    def generate(self, prompt: str, system_message: Optional[str] = None, **kwargs) -> str:
        """Generate response using OpenAI."""
        messages = []
        
        if system_message:
            messages.append({"role": "system", "content": system_message})
        
        messages.append({"role": "user", "content": prompt})
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                **{**self.kwargs, **kwargs}
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"[ERROR] OpenAI generation failed: {e}")
            raise LLMGenerationError(f"openai generation failed: {e}") from e
    
    def get_provider_name(self) -> str:
        return f"openai:{self.model}"


class LiteLLMProvider(OpenAIProvider):
    """OpenAI-compatible LiteLLM gateway provider."""

    def __init__(self, model: str = DEFAULT_PROVIDER_MODELS["litellm"], api_key: Optional[str] = None,
                 base_url: Optional[str] = None, **kwargs):
        api_key = api_key or os.getenv("LITELLM_API_KEY")
        base_url = base_url or os.getenv("LITELLM_BASE_URL") or os.getenv("LITELLM_API_BASE") or os.getenv("OPENAI_BASE_URL")
        if not base_url:
            raise ValueError(
                "LiteLLM base URL not provided. Set LITELLM_BASE_URL or pass base_url in config."
            )
        super().__init__(model=model, api_key=api_key, base_url=base_url, **kwargs)
        self.base_url = base_url

    def get_provider_name(self) -> str:
        return f"litellm:{self.model}"

class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider implementation."""
    
    def __init__(self, model: str = DEFAULT_PROVIDER_MODELS["anthropic"], api_key: Optional[str] = None, **kwargs):
        self.model = model
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.kwargs = kwargs
        
        if not self.api_key:
            raise ValueError("Anthropic API key not provided. Set ANTHROPIC_API_KEY environment variable or pass api_key parameter.")
        
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=self.api_key)
        except ImportError:
            raise ImportError("Anthropic not available. Install with: pip install anthropic")
    
    def generate(self, prompt: str, system_message: Optional[str] = None, **kwargs) -> str:
        """Generate response using Anthropic Claude."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                system=system_message or "",
                messages=[{"role": "user", "content": prompt}],
                **{**self.kwargs, **kwargs}
            )
            return response.content[0].text
        except Exception as e:
            print(f"[ERROR] Anthropic generation failed: {e}")
            raise LLMGenerationError(f"anthropic generation failed: {e}") from e
    
    def get_provider_name(self) -> str:
        return f"anthropic:{self.model}"

class LLMManager:
    """Manager class for LLM providers with unified interface."""
    
    def __init__(self, provider_config: Dict[str, Any]):
        """
        Initialize LLM manager with provider configuration.
        
        Args:
            provider_config: Dictionary with provider settings
                Example: {
                    "provider": "ollama",
                    "model": "gemma2:2b",
                    "personality": "helpful"
                }
        """
        self.provider_config = provider_config
        self.provider = self._create_provider()
        self.personality = provider_config.get("personality")
    
    def _create_provider(self) -> LLMProvider:
        """Create provider instance based on configuration."""
        provider_type = self.provider_config.get("provider", "ollama").lower()
        model = self.provider_config.get("model") or default_model_for_provider(provider_type)
        provider_kwargs = {
            key: value
            for key, value in self.provider_config.items()
            if key not in {"provider", "model", "personality"} and value is not None
        }
        
        if provider_type == "ollama":
            return OllamaProvider(model=model, **provider_kwargs)
        elif provider_type == "openai":
            return OpenAIProvider(model=model, **provider_kwargs)
        elif provider_type == "litellm":
            return LiteLLMProvider(model=model, **provider_kwargs)
        elif provider_type == "anthropic":
            return AnthropicProvider(model=model, **provider_kwargs)
        else:
            raise ValueError(f"Unsupported provider: {provider_type}")
    
    def generate(self, prompt: str, system_message: Optional[str] = None, **kwargs) -> str:
        """Generate response using the configured provider."""
        # Add personality to system message if specified
        if self.personality and not system_message:
            system_message = f"You are a {self.personality} assistant."
        elif self.personality and system_message:
            system_message = f"You are a {self.personality} assistant.\n\n{system_message}"
        
        return self.provider.generate(prompt, system_message, **kwargs)
    
    def get_provider_info(self) -> str:
        """Get information about the current provider."""
        return self.provider.get_provider_name()
    
    def summarize_text(self, text: str, max_chars: int = 6000, question: Optional[str] = None) -> str:
        """Summarize text, answering `question` when one is supplied.

        Branch summaries are the highest-weighted evidence in the final report
        prompt. A question-free "summarize this text" prompt produces a generic
        page digest, so the report is assembled from material that never
        addressed the branch's research question.
        """
        if len(text) <= max_chars:
            return self.generate(_summary_prompt(text, question))

        # If text is longer than max_chars, chunk it
        chunks = [text[i:i+max_chars] for i in range(0, len(text), max_chars)]
        summaries = []

        for i, chunk in enumerate(chunks):
            prompt = _summary_prompt(chunk, question, part=(i + 1, len(chunks)))
            summary = self.generate(prompt)
            summaries.append(summary)
            time.sleep(1)  # Rate limiting

        combined = "\n".join(summaries)
        if len(combined) > max_chars:
            prompt = _summary_prompt(combined, question, combining=True)
            combined = self.generate(prompt)

        return combined
    
    def enhance_query(self, query: str) -> str:
        """Enhance a query using chain-of-thought reasoning."""
        prompt = (
            f"Original Query: {query}\n\n"
            "Please enhance this query by:\n"
            "1. Adding specific context and constraints\n"
            "2. Clarifying the scope and objectives\n"
            "3. Specifying the desired output format\n"
            "4. Including relevant technical details\n\n"
            "After your reasoning, output only the final enhanced query on a single line - SHORT AND CONCISE.\n"
            "Provide your reasoning, and at the end output the line 'Final Enhanced Query:' followed by the enhanced query."
        )
        
        raw_output = self.generate(prompt)
        return self._extract_final_query(raw_output)
    
    def _extract_final_query(self, text: str) -> str:
        """Extract the final enhanced query from the response."""

        lines = text.split('\n')
        for line in lines:
            if 'Final Enhanced Query:' in line:
                return line.split('Final Enhanced Query:')[-1].strip()
        return text.strip()
    
    def generate_final_answer(self, aggregation_prompt: str) -> str:
        """Generate the final RAG answer."""
        print(f"[INFO] Performing final RAG generation using: {self.get_provider_info()}")
        return self.generate(aggregation_prompt)
    
    def follow_up_conversation(self, follow_up_prompt: str) -> str:
        """Handle follow-up conversations."""
        return self.generate(follow_up_prompt)

    def generate_json_schema(
        self,
        prompt: str,
        schema_name: str,
        schema: Dict[str, Any],
        system_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate schema-constrained JSON through OpenAI-compatible kwargs."""
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "schema": schema,
                "strict": True,
            },
        }
        raw = self.generate(prompt, system_message=system_message, response_format=response_format)
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("structured response was not a JSON object")
        return parsed

# Factory function for easy provider creation
def create_llm_manager(provider: str = "ollama", model: Optional[str] = None,
                      personality: Optional[str] = None, **kwargs) -> LLMManager:
    """Create an LLM manager with the specified configuration."""
    config = {
        "provider": provider,
        "model": model or default_model_for_provider(provider),
        "personality": personality,
        **kwargs
    }
    return LLMManager(config)
