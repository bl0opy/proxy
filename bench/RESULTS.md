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

## nimble vs Laya vs Jev — `bench/compare.py`

Same 17 cases, 10 intents. "First-seen" = prompt never sent before (what a real utterance costs).

| backend | first-seen median | accuracy | notes |
|---|---|---|---|
| nimble 9B, Ollama Q8 | 1271 ms | 16/17 | 68 ms only on an exact repeat |
| Laya 421M, MPS, criteria with descriptions | ~54 ms | 5/17 | probabilities flat (~0.3) |
| Laya 421M, MPS, bare labels | 39 ms | 10/17 | wrong at 0.96 confidence on "go to github dot com" |
| Laya typed-decisions 421M | ~56 ms | 6/17 | |
| Jev 1.14 API | not run | — | needs `TYPESAFE_API_KEY` |

- Laya is fast enough but not accurate enough to be the router, and its confidence
  does not reliably flag its own mistakes, so gating on it lets wrong actions through.
- Jev price (docs.typesafe.ai/models, 2026-10-20): $0.042 per million input tokens,
  output free. A ~450-token decision costs ~$0.000019; 1,000 commands/day ≈ $0.57/month.
