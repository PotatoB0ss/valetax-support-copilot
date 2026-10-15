# Business-case numbers (generated)

Volume 10,000/month · baseline 6.0 min/ticket · agent $15/h (base case). Measured: draft quality (judge), routing, $/ticket. Assumed: see assumptions.json.

| Config | Gate | Usable drafts | Min saved / ticket | Hours saved / mo | FTE | LLM $/mo | Total cost $/mo | Value $/mo | Net $/mo | Payback (mo) | Break-even agent $/h |
|---|---|---|---|---|---|---|---|---|---|---|---|
| p1-haiku | FAIL | 100% | 2.82 | 470 | 2.9 | 3 | 2,756 | 7,056 | 4,300 | 2.8 | 5.86 |
| p1-sonnet | PASS | 100% | 2.84 | 474 | 3.0 | 62 | 2,817 | 7,104 | 4,288 | 2.8 | 5.95 |
| p1-opus | FAIL | 100% | 3.03 | 505 | 3.2 | 126 | 2,883 | 7,576 | 4,693 | 2.6 | 5.71 |
| p1-haiku-cascade | FAIL | 100% | 2.76 | 460 | 2.9 | 4 | 2,757 | 6,894 | 4,137 | 2.9 | 6.0 |
| p2-staged | FAIL | 98% | 2.94 | 491 | 3.1 | 57 | 2,811 | 7,360 | 4,549 | 2.6 | 5.73 |

## Sensitivity: net $/month

| Config | agent $8/h | agent $15/h | agent $30/h | 5k tickets | 10k tickets | 20k tickets | 50k tickets | 100k tickets |
|---|---|---|---|---|---|---|---|---|
| p1-haiku | 1,007 | 4,300 | 11,355 | 774 | 4,300 | 11,352 | 32,509 | 67,771 |
| p1-sonnet | 972 | 4,288 | 11,392 | 767 | 4,288 | 11,330 | 32,456 | 67,667 |
| p1-opus | 1,158 | 4,693 | 12,269 | 968 | 4,693 | 12,143 | 34,493 | 71,742 |
| p1-haiku-cascade | 920 | 4,137 | 11,031 | 692 | 4,137 | 11,027 | 31,698 | 66,148 |
| p2-staged | 1,114 | 4,549 | 11,909 | 897 | 4,549 | 11,852 | 33,762 | 70,278 |
