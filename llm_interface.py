# llm_interface.py

import os
import time
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import json

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
            return f"Error generating response: {e}"
    
    def get_provider_name(self) -> str:
        return f"ollama:{self.model}"

class OpenAIProvider(LLMProvider):
    """OpenAI provider implementation."""
    
    def __init__(self, model: str = "gpt-3.5-turbo", api_key: Optional[str] = None, **kwargs):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.kwargs = kwargs
        
        if not self.api_key:
            raise ValueError("OpenAI API key not provided. Set OPENAI_API_KEY environment variable or pass api_key parameter.")
        
        try:
            import openai
            self.client = openai.OpenAI(api_key=self.api_key)
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
            return f"Error generating response: {e}"
    
    def get_provider_name(self) -> str:
        return f"openai:{self.model}"

class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider implementation."""
    
    def __init__(self, model: str = "claude-3-sonnet-20240229", api_key: Optional[str] = None, **kwargs):
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
            return f"Error generating response: {e}"
    
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
        model = self.provider_config.get("model", "gemma2:2b")
        
        if provider_type == "ollama":
            return OllamaProvider(model=model)
        elif provider_type == "openai":
            return OpenAIProvider(model=model)
        elif provider_type == "anthropic":
            return AnthropicProvider(model=model)
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
    
    def summarize_text(self, text: str, max_chars: int = 6000) -> str:
        """Summarize text with automatic chunking for long content."""
        if len(text) <= max_chars:
            prompt = f"Please summarize the following text succinctly:\n\n{text}"
            return self.generate(prompt)
        
        # If text is longer than max_chars, chunk it
        chunks = [text[i:i+max_chars] for i in range(0, len(text), max_chars)]
        summaries = []
        
        for i, chunk in enumerate(chunks):
            prompt = f"Summarize part {i+1}/{len(chunks)}:\n\n{chunk}"
            summary = self.generate(prompt)
            summaries.append(summary)
            time.sleep(1)  # Rate limiting
        
        combined = "\n".join(summaries)
        if len(combined) > max_chars:
            prompt = f"Combine these summaries into one concise summary:\n\n{combined}"
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
        import re
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

# Factory function for easy provider creation
def create_llm_manager(provider: str = "ollama", model: str = "gemma2:2b", 
                      personality: Optional[str] = None, **kwargs) -> LLMManager:
    """Create an LLM manager with the specified configuration."""
    config = {
        "provider": provider,
        "model": model,
        "personality": personality,
        **kwargs
    }
    return LLMManager(config)

# Backward compatibility functions
def call_gemma(prompt: str, model: str = "gemma2:2b", personality: Optional[str] = None) -> str:
    """Backward compatibility function for call_gemma."""
    manager = create_llm_manager("ollama", model, personality)
    return manager.generate(prompt)

def rag_final_answer(aggregation_prompt: str, rag_model: str = "gemma", personality: Optional[str] = None) -> str:
    """Backward compatibility function for rag_final_answer."""
    manager = create_llm_manager("ollama", "gemma2:2b", personality)
    return manager.generate_final_answer(aggregation_prompt)

def summarize_text(text: str, max_chars: int = 6000, personality: Optional[str] = None) -> str:
    """Backward compatibility function for summarize_text."""
    manager = create_llm_manager("ollama", "gemma2:2b", personality)
    return manager.summarize_text(text, max_chars)

def chain_of_thought_query_enhancement(query: str, personality: Optional[str] = None) -> str:
    """Backward compatibility function for chain_of_thought_query_enhancement."""
    manager = create_llm_manager("ollama", "gemma2:2b", personality)
    return manager.enhance_query(query)

def follow_up_conversation(follow_up_prompt: str, personality: Optional[str] = None) -> str:
    """Backward compatibility function for follow_up_conversation."""
    manager = create_llm_manager("ollama", "gemma2:2b", personality)
    return manager.follow_up_conversation(follow_up_prompt)
