# nimble latency — M1 Max 32 GB, Ollama 0.35.1, nimble Q8_0 (9B)

Single-token classification, `num_predict: 1`, raw prompt in the trained format.

| scenario | prompt tokens | median wall | accuracy |
|---|---|---|---|
| cold start (load + first call) | 443 | 7610 ms | — |
| 10 intents, trained layout | 447 | 1231 ms | 16/17 |
| 10 intents, schema-first layout | 447 | 1277 ms | 16/17 |
| 10 intents, no choice descriptions | 276 | 791 ms | 13/17 |
| 26 intents, trained layout | 925 | 2703 ms | 16/17 |
| 26 intents, schema-first layout | 925 | 1604 ms | 16/17 |
| identical prompt repeated | 443 | 63 ms | — |

- Prefill runs at ~370 tok/s; decode of the single code is ~0 ms. Latency is prompt length.
- Moving the schema ahead of the context does not buy prefix-cache reuse in Ollama:
  Qwen3.5 is a hybrid (linear-attention) model, so only an exact repeat hits the cache.
- Choice descriptions are worth their tokens: dropping them cut latency 36% but lost 3 cases.
