type Location = { section_position: number | null; character_offset: number | null };
type Unit = Location & { kind: "front_matter" | "chapter" };
type Entry = Location & { title: string | null };

export function chapterTitles(units: Unit[], entries: Entry[]): string[] {
  return units
    .filter((unit) => unit.kind === "chapter")
    .map((unit, index) => {
      const title = entries
        .find(
          (entry) =>
            entry.section_position === unit.section_position &&
            entry.character_offset === unit.character_offset &&
            entry.title?.trim(),
        )
        ?.title?.trim();
      const number = `Chapter ${index + 1}`;
      if (!title) return number;
      return new RegExp(`^chapter\\s+${index + 1}\\b`, "i").test(title)
        ? title
        : `${number}: ${title}`;
    });
}
