# Retrieval evaluation

The evaluation uses *The Inland Compass*, an original, fictional six-chapter story released under CC0. The first two chapters share one EPUB section. The script builds and imports the EPUB, confirms known chapter starts, and uses a temporary library; it does not touch the reader's books or progress. A copy of the sample is in `examples/`.

Run the offline keyword evaluation from the project root:

```sh
uv run python scripts/evaluate_retrieval.py
```

To include hybrid search, first use **Download model** in the app, then run:

```sh
uv run python scripts/evaluate_retrieval.py --hybrid
```

The hybrid run requires the existing model cache and does not initiate a download. It reports an error if the model is unavailable. Both runs print JSON and exit nonzero if a boundary check fails. They measure process CPU time and elapsed time for the quality questions, including one repeated query; timings vary by computer and are not a laptop benchmark.

For quality, six authored questions are run against the finished book. Each has one exact expected source phrase. Recall@1 and recall@3 are the fraction with that phrase in the first one or three passages. MRR@5 averages the reciprocal of its first result rank, counting a miss as zero. For boundary safety, six searches run at four progress settings. Every returned passage must exactly match the independently constructed allowed source text at its stated offset, including when a boundary splits a section. These are retrieval checks, not proof that future generated answers are supported or spoiler-free.

On 2026-11-04, the keyword run returned ranks `[1, 1, 1, 1, 2, 1]`: recall@1 **5/6**, recall@3 **6/6**, MRR@5 **0.917**, and **0 violations in 24 boundary checks**. Its median elapsed time was approximately 0.002 seconds on the development environment; do not generalize that timing. Hybrid quality and speed have **not** been measured with the real model.

This deliberately tiny fixture is useful for regression checks and comparing changes, not for claiming production accuracy. Its questions, story and expected phrases are authored together, and it does not cover the diversity, structure, length or language of real books. Additional independent books, paraphrases, adversarial inputs and measured hardware runs are needed.

## Offline answer safety evaluation

Run the local API evaluation against simulated OpenAI responses:

```sh
uv run pytest -q tests/test_answer_evaluation.py
```

The evaluation imports the same synthetic EPUB into a temporary library and makes requests to the real local answer API. It runs six authored questions and two adversarial questions at four reading-progress settings: **32 cases**. For each model request, the test compares every supplied passage with the independently authored text permitted at that progress. The simulated model returns a fabricated citation; the API must reject it without exposing the fake answer. If retrieval finds no passages, the API must return its fixed insufficient-evidence response without a model request. The test also requires a model request when the authored expected evidence is already within the boundary.

A further **six cases** use the finished book and simulated responses that cite each question's known source phrase. They check that the local API returns the expected quote and its original section and character offset. On 2026-11-05, all **38 cases passed**, with no forbidden passages or fabricated responses observed in these cases.

The model responses are scripted, and the six positive responses are given the expected source phrase. These checks do not measure whether a real model finds the right answer, supports every claim, or avoids generating spoilers. The sample is tiny and authored alongside the questions; the results are regression evidence, not a representative benchmark. The tests send no book text to OpenAI and use isolated temporary storage.

## Offline recap safety evaluation

The same local API evaluation also checks **36 recap scenarios**: six chapter selections, three reading-progress settings, and both single-chapter and cumulative scopes. The authored sample includes two chapters in one EPUB section, so the checks exercise an internal chapter boundary as well as section boundaries.

For the **20 completed-chapter scenarios**, the test compares the entire text sent to the simulated model with independently authored expected text for the chosen scope, verifies a known source quote and its original offset, and repeats the request with a fabricated citation that must be rejected. For the **16 unread-chapter scenarios**, it expects a client error and no model request. On 2026-11-05, all 36 scenarios passed.

These short synthetic chapters do not evaluate multi-stage long recaps. The responses are scripted, so these results do not measure recap completeness, factual support, or a real model's spoiler behavior. Existing long-recap failure and boundary tests run as part of the backend test suite; live-model evaluation remains outstanding.
