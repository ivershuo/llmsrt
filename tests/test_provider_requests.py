import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import llmsrt


class ProviderRequestTests(unittest.TestCase):
    def args(self, provider="openai", *extra):
        args = llmsrt.argument_parser().parse_args([
            "--provider", provider, "--api-key-env", "LLMSRT_TEST_KEY", *extra,
        ])
        llmsrt.configure_llm(args)
        return args

    def test_only_openai_and_deepseek_have_presets(self):
        self.assertEqual(set(llmsrt.PROVIDERS), {"openai", "deepseek"})
        for provider in llmsrt.PROVIDERS:
            with self.subTest(provider=provider):
                args = self.args(provider)
                self.assertEqual(args.model, llmsrt.PROVIDERS[provider]["model"])
                self.assertEqual(args.base_url, llmsrt.PROVIDERS[provider]["base_url"])

    def test_translation_and_quip_requests_omit_all_tool_parameters(self):
        for provider in ("openai", "deepseek", "custom", "local"):
            for prompt, limit in ((llmsrt.TRANSLATION_PROMPT, None), (llmsrt.QUIP_PROMPT, 1024)):
                with self.subTest(provider=provider, prompt=prompt[:20]):
                    extra = [] if provider in llmsrt.PROVIDERS else [
                        "--model", "local-model", "--base-url", "https://example.invalid/v1",
                    ]
                    args = self.args(provider, *extra)
                    with patch.dict("os.environ", {"LLMSRT_TEST_KEY": "test-key"}):
                        request, _ = llmsrt.make_llm_request(args, prompt, {"items": []}, token_limit=limit)
                    body = json.loads(request.data)
                    for key in llmsrt.TOOL_PARAMETERS:
                        self.assertNotIn(key, body)
                    token_key = "max_completion_tokens" if provider == "openai" else "max_tokens"
                    self.assertEqual(body[token_key], args.max_tokens if limit is None else limit)

    def test_custom_provider_requires_explicit_configuration(self):
        for provider in ("custom", "glm"):
            with self.subTest(provider=provider), patch.dict("os.environ", {}, clear=True):
                args = llmsrt.argument_parser().parse_args(["--provider", provider])
                with self.assertRaisesRegex(llmsrt.LlmsrtError, "requires.*--model.*--base-url.*--api-key-env"):
                    llmsrt.configure_llm(args)
        self.assertEqual(self.args(" OpenAI ").provider, "openai")

    def test_tools_cannot_be_injected_through_extra_body(self):
        for provider in ("openai", "deepseek", "custom"):
            for key in llmsrt.TOOL_PARAMETERS:
                with self.subTest(provider=provider, key=key):
                    extra = [] if provider in llmsrt.PROVIDERS else [
                        "--model", "local-model", "--base-url", "https://example.invalid/v1",
                    ]
                    with self.assertRaisesRegex(llmsrt.LlmsrtError, "tool use is disabled"):
                        self.args(provider, *extra, "--extra-body", json.dumps({key: "auto"}))
        args = self.args("deepseek", "--extra-body", '{"thinking":{"type":"disabled"}}')
        self.assertEqual(args.extra_body, {"thinking": {"type": "disabled"}})

    def test_request_works_with_gateway_that_rejects_tool_choice_without_tools(self):
        args = self.args()
        translator = llmsrt.LLMTranslator(args, Mock())
        result = {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}

        def gateway(request, **kwargs):
            body = json.loads(request.data)
            if "tool_choice" in body and not body.get("tools"):
                raise HTTPError(request.full_url, 400, "invalid_request_error", {}, io.BytesIO(
                    b"tool_choice is only allowed when tools are specified"))
            return io.BytesIO(json.dumps(result).encode())

        with patch.dict("os.environ", {"LLMSRT_TEST_KEY": "test-key"}), \
                patch.object(translator.opener, "open", side_effect=gateway) as api:
            self.assertEqual(translator.request({"items": [{"id": 1, "text": "Hello"}]}), result)
        self.assertEqual(api.call_count, 1)

    def test_unexpected_tool_calls_are_rejected_even_with_valid_text(self):
        requested = [{"id": 1, "targets": ["ja"]}]
        for key, value in (("tool_calls", [{"type": "function", "function": {"name": "search"}}]),
                           ("function_call", {"name": "search", "arguments": "{}"})):
            with self.subTest(key=key):
                result = {"choices": [{"finish_reason": "stop", "message": {
                    key: value, "content": json.dumps({"items": [{
                        "id": 1, "translations": {"ja": "こんにちは"}}]})}}]}
                with self.assertRaisesRegex(llmsrt.LlmsrtError, "tool use is disabled"):
                    llmsrt.LLMTranslator.validate(result, requested)
                result["choices"][0]["message"]["content"] = json.dumps({
                    "quips": ["正在给译文调低音量，让语气轻轻落地。"]})
                self.assertEqual(llmsrt.validate_model_quips(result, "Coffee?"), ())


if __name__ == "__main__":
    unittest.main()
