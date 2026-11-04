# Answer and citation safety

The backend citation validator accepts a generated JSON answer and the retrieved passages that were supplied to the model. Each citation contains a zero-based passage index and an exact, nonblank quote. A valid result identifies the source section and the quote's character offset. If the response is malformed, an answer is blank or uncited, an index is invalid, or any quote is absent, the entire answer is rejected.

This is only one safeguard. Matching a quote does not prove that the answer's claims are supported, or that the passages are within the reader's current boundary. Before connecting the validator to questions, the caller must retrieve only eligible text, verify the boundary again after generation, withhold results if it changed, and handle insufficient evidence. Do not stream unvalidated output to the reader. The validator does not yet power an API or user interface.
