import { z } from "zod";

const sectionSchema = z.object({ position: z.number().int().nonnegative(), text: z.string() });
const unitSchema = z.object({
  kind: z.enum(["front_matter", "chapter"]),
  section_position: z.number().int().nonnegative(),
  character_offset: z.number().int().nonnegative(),
});
export type BookSection = z.infer<typeof sectionSchema>;
export type ReadingUnit = z.infer<typeof unitSchema>;

async function checked(response: Response): Promise<Response> {
  if (response.ok) return response;
  const message = z
    .object({ detail: z.string() })
    .safeParse(await response.json().catch(() => null));
  throw new Error(message.success ? message.data.detail : "The request could not be completed.");
}

export async function loadChapterReview(bookId: string) {
  const root = `/api/books/${encodeURIComponent(bookId)}`;
  const [sectionsResponse, unitsResponse] = await Promise.all([
    fetch(`${root}/sections`),
    fetch(`${root}/reading-units`),
  ]);
  const sections = z.array(sectionSchema).parse(await (await checked(sectionsResponse)).json());
  const units = z.array(unitSchema).parse(await (await checked(unitsResponse)).json());
  return { sections, units };
}

export async function saveChapterReview(bookId: string, units: ReadingUnit[]) {
  await checked(
    await fetch(`/api/books/${encodeURIComponent(bookId)}/reading-units`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ units }),
    }),
  );
}
