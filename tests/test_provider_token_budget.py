"""The provider output budget. In the Preview evaluation five answers were cut off mid-JSON (Cerebras stopped at exactly 4096 tokens with ~3,000 of them
reasoning; Gemini 2.5 spent ~3,930 on thinking and had ~70-150 left) and were rejected as "malformed JSON". Offline: no network, no model."""
import json
import unittest

from backend import grounded_answer, providers


class Resp:
    def __init__(self, body, status=200):
        self.status_code, self._body, self.headers, self.text = status, body, {}, json.dumps(body)

    def json(self):
        return self._body


def capture(provider_cls, *args, reply, **kw):
    seen = {}

    def http(url, headers=None, json=None, timeout=None):
        seen["body"], seen["url"] = json, url
        return Resp(reply)

    return provider_cls(*args, http=http, **kw), seen


OPENAI_OK = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30, "completion_tokens_details": {"reasoning_tokens": 5}}}
OPENAI_CUT = {"choices": [{"message": {"content": '{"answer": "cut'}, "finish_reason": "length"}],
              "usage": {"prompt_tokens": 10, "completion_tokens": 4096, "total_tokens": 4106, "completion_tokens_details": {"reasoning_tokens": 3144}}}
GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": "{}"}]}, "finishReason": "STOP"}],
             "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 20, "totalTokenCount": 30, "thoughtsTokenCount": 5}}
GEMINI_CUT = {"candidates": [{"content": {"parts": [{"text": '{"answer": "cu'}]}, "finishReason": "MAX_TOKENS"}],
              "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 71, "totalTokenCount": 4009, "thoughtsTokenCount": 3928}}


class OutputBudget(unittest.TestCase):
    def test_default_budget_leaves_room_after_reasoning(self):
        s = providers.ProviderSettings()
        self.assertEqual(s.max_output_tokens, 8192)  # the 4096 that truncated answers is no longer the default
        self.assertEqual(providers.ProviderSettings.from_env({}).max_output_tokens, 8192)

    def test_env_still_overrides_and_is_clamped(self):
        self.assertEqual(providers.ProviderSettings.from_env({"PROVIDER_MAX_OUTPUT_TOKENS": "2048"}).max_output_tokens, 2048)
        self.assertEqual(providers.ProviderSettings.from_env({"PROVIDER_MAX_OUTPUT_TOKENS": "999999"}).max_output_tokens, 32768)
        self.assertEqual(providers.ProviderSettings.from_env({"PROVIDER_MAX_OUTPUT_TOKENS": "x"}).max_output_tokens, 8192)

    def test_every_provider_is_sent_the_new_budget(self):
        orch = providers.ProviderOrchestrator.from_settings(providers.ProviderSettings.from_env(
            {"GROQ_API_KEY": "k" * 20, "CEREBRAS_API_KEY": "k" * 20, "GEMINI_API_KEY": "k" * 20}))
        self.assertEqual({p.name: p.max_output_tokens for p in orch.providers if p.name != "ollama"}, {"groq": 8192, "cerebras": 8192, "gemini": 8192})
        groq, seen = capture(providers.GroqProvider, "k" * 20, "m", 30, 8192, reply=OPENAI_OK)
        groq.send("p")
        self.assertEqual(seen["body"]["max_tokens"], 8192)


class GeminiThinkingBudget(unittest.TestCase):
    def body(self, model, budget):
        g, seen = capture(providers.GeminiProvider, "k" * 20, model, 30, 8192, reply=GEMINI_OK, thinking_budget=budget)
        g.send("p")
        return seen["body"]["generationConfig"]

    def test_gemini_25_gets_a_thinking_cap_that_leaves_room_for_the_json(self):
        cfg = self.body("gemini-2.5-flash", 2048)
        self.assertEqual(cfg["thinkingConfig"], {"thinkingBudget": 2048})
        self.assertLess(cfg["thinkingConfig"]["thinkingBudget"], cfg["maxOutputTokens"])
        self.assertEqual(cfg["responseMimeType"], "application/json")  # the structured-output settings are unchanged
        self.assertIn("responseJsonSchema", cfg)

    def test_other_models_and_a_zero_budget_send_no_thinking_field(self):
        self.assertNotIn("thinkingConfig", self.body("gemini-2.0-flash", 2048))  # models without thinking reject the field
        self.assertNotIn("thinkingConfig", self.body("gemini-2.5-flash", 0))      # 0 = the model's own default

    def test_default_and_env(self):
        self.assertEqual(providers.ProviderSettings().gemini_thinking_budget, 2048)
        self.assertEqual(providers.ProviderSettings.from_env({"GEMINI_THINKING_BUDGET": "0"}).gemini_thinking_budget, 0)
        self.assertEqual(providers.ProviderSettings.from_env({"GEMINI_THINKING_BUDGET": "999999"}).gemini_thinking_budget, 24576)


class TruncationIsVisible(unittest.TestCase):
    def usage(self, cls, reply, *args):
        p, _ = capture(cls, "k" * 20, "m", 30, 8192, *args, reply=reply)
        return p.send_full("p")[1]

    def test_a_cut_off_answer_is_flagged_in_the_call_record(self):
        for cls, cut, ok in ((providers.GroqProvider, OPENAI_CUT, OPENAI_OK), (providers.CerebrasProvider, OPENAI_CUT, OPENAI_OK),
                             (providers.GeminiProvider, GEMINI_CUT, GEMINI_OK)):
            with self.subTest(provider=cls.__name__):
                self.assertTrue(self.usage(cls, cut)["truncated"])
                self.assertNotIn("truncated", self.usage(cls, ok))  # a normal answer's record is exactly what it was

    def test_a_cut_off_answer_is_still_rejected_by_the_validator(self):
        """Nothing is repaired or accepted: the raw text is still checked, and a half-written JSON object fails closed."""
        parsed, errors = grounded_answer.parse_response(OPENAI_CUT["choices"][0]["message"]["content"])
        self.assertIsNone(parsed)
        self.assertEqual(errors, ["malformed JSON"])


if __name__ == "__main__":
    unittest.main()
