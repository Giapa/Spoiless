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
