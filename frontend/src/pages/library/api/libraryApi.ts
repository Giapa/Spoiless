import { z } from "zod";

const bookSchema = z.object({
  id: z.string().uuid(),
  title: z.string(),
  section_count: z.number().int().positive(),
  chapters_confirmed: z.boolean(),
});

export type Book = z.infer<typeof bookSchema>;

async function ensureSuccess(response: Response): Promise<Response> {
  if (response.ok) return response;
  const result = z
    .object({ detail: z.string() })
    .safeParse(await response.json().catch(() => null));
  throw new Error(result.success ? result.data.detail : "The request could not be completed.");
}

export async function fetchBooks(): Promise<Book[]> {
  const response = await ensureSuccess(await fetch("/api/books"));
  return z.array(bookSchema).parse(await response.json());
}

export async function importBook(file: File): Promise<Book> {
  const response = await ensureSuccess(
    await fetch("/api/books", {
      method: "POST",
      headers: { "Content-Type": "application/epub+zip" },
      body: file,
    }),
  );
  return bookSchema.parse(await response.json());
}

export async function deleteBook(bookId: string): Promise<void> {
  await ensureSuccess(
    await fetch(`/api/books/${encodeURIComponent(bookId)}`, { method: "DELETE" }),
  );
}
