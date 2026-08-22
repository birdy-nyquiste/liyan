# Use the DeepSeek Responses API for 知言

知言 runs use DeepSeek through a replaceable server-side provider adapter and the OpenAI-compatible `POST /responses` endpoint at `https://api.deepseek.com`. The adapter uses the server-executed `web_search` tool for external evidence and `text.format` with `type: "json_schema"` for the typed report envelope. Successful provider output is still untrusted input: deterministic application validation must reject invalid report structure, references, verdicts, and evidence before an immutable 知言报告 is accepted.

The integration must preserve DeepSeek's stateless contract. Responses and conversations are not stored by the provider, `store` is always `false`, and `previous_response_id` and server-side conversations are unsupported. Each request therefore supplies its complete approved input, while 立言阁 owns Execution state, immutable request metadata, provider-result evidence, retry policy, and recovery. Queue messages contain only the Execution identity rather than source content or provider payloads.

The built-in `web_search` and versioned `web_search_2025_08_26` tool types execute on DeepSeek's server and emit `web_search_call` output items for `search`, `open_page`, and `find_in_page` actions. Server-side search auto-continuation is capped at ten rounds; `search_context_size` and `user_location` are currently ignored. The adapter must not depend on those ignored controls and must preserve the search actions and evidence actually used for report validation and audit.

The confirmed MVP model is `deepseek-v4-flash`, matching the 服务端 模块总纲 and Technical Spec §10. The model identifier remains server configuration, so `deepseek-v4-pro` can be evaluated as a higher-quality candidate without changing the domain contract; that evaluation is the open task recorded in Technical Spec §11.1. API keys and account balance are deployment configuration and must never be stored in source control or exposed to the browser.

Strict structured output accepts only a subset of JSON Schema, so the provider-facing report schema omits string-tightening keywords such as `minLength`. Those constraints are still enforced, but by deterministic application acceptance rather than by the provider.

References, verified 2026-08-22:

- [DeepSeek Responses API reference](https://api-docs.deepseek.com/api/create-response)
- [DeepSeek Responses API compatibility guide](https://api-docs.deepseek.com/guides/responses_api)
