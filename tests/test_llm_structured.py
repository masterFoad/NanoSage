from __future__ import annotations

import unittest

from llm_interface import LLMGenerationError, LLMManager


class FakeProvider:
    def __init__(self, response: str):
        self.response = response
        self.kwargs = None

    def generate(self, prompt, system_message=None, **kwargs):
        self.kwargs = kwargs
        return self.response

    def get_provider_name(self):
        return "fake"


class LLMStructuredTests(unittest.TestCase):
    def test_generate_json_schema_passes_response_format(self):
        manager = LLMManager.__new__(LLMManager)
        manager.personality = None
        manager.provider = FakeProvider('{"questions":["A?"]}')

        parsed = manager.generate_json_schema(
            "prompt",
            "schema_name",
            {"type": "object"},
        )

        self.assertEqual(parsed, {"questions": ["A?"]})
        response_format = manager.provider.kwargs["response_format"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertEqual(response_format["json_schema"]["name"], "schema_name")
        self.assertTrue(response_format["json_schema"]["strict"])

    def test_generate_json_schema_propagates_provider_failure(self):
        class FailingProvider:
            def generate(self, prompt, system_message=None, **kwargs):
                raise LLMGenerationError("unsupported")

        manager = LLMManager.__new__(LLMManager)
        manager.personality = None
        manager.provider = FailingProvider()

        # Providers used to return the failure as text, which then parsed as a
        # report or a branch summary. It must surface as an exception instead.
        with self.assertRaisesRegex(LLMGenerationError, "unsupported"):
            manager.generate_json_schema("prompt", "schema_name", {"type": "object"})

    def test_generate_json_schema_rejects_non_object_response(self):
        manager = LLMManager.__new__(LLMManager)
        manager.personality = None
        manager.provider = FakeProvider('["not", "an", "object"]')

        with self.assertRaisesRegex(ValueError, "not a JSON object"):
            manager.generate_json_schema("prompt", "schema_name", {"type": "object"})


if __name__ == "__main__":
    unittest.main()
