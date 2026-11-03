import type { NavigationEntry, ReadingUnit } from "../api/chapterReviewApi";

export type EntryChoice = "" | "chapter" | "front_matter" | "ignore";

/** Convert explicit choices into boundaries without guessing or reordering entries. */
export function buildReadingUnits(
  entries: NavigationEntry[],
  choices: EntryChoice[],
  prefixIsFrontMatter: boolean,
): ReadingUnit[] {
  if (
    entries.length === 0 ||
    choices.length !== entries.length ||
    choices.some((choice) => !choice)
  ) {
    throw new Error("Choose what to do with every entry.");
  }
  const units: ReadingUnit[] = [];
  for (const [index, entry] of entries.entries()) {
    const choice = choices[index];
    if (choice === "ignore") continue;
    if (choice !== "chapter" && choice !== "front_matter")
      throw new Error("Choose what to do with every entry.");
    if (entry.section_position === null || entry.character_offset === null) {
      throw new Error(
        "An entry without a location cannot be used. Ignore it or use manual review.",
      );
    }
    units.push({
      kind: choice,
      section_position: entry.section_position,
      character_offset: entry.character_offset,
    });
  }
  if (!units.length) throw new Error("Select at least one chapter.");
  const first = units[0]!;
  const startsAtBeginning = first.section_position === 0 && first.character_offset === 0;
  if (!startsAtBeginning) {
    if (!prefixIsFrontMatter)
      throw new Error(
        "Mark the text before the first selected entry as front matter, or use manual review.",
      );
    units.unshift({ kind: "front_matter", section_position: 0, character_offset: 0 });
  } else if (prefixIsFrontMatter) {
    throw new Error(
      "There is no text before the first selected entry. Clear the front matter option.",
    );
  }
  if (!units.some((unit) => unit.kind === "chapter"))
    throw new Error("Select at least one chapter.");
  for (const [index, unit] of units.entries()) {
    if (unit.kind === "front_matter" && index !== 0)
      throw new Error("Front matter must be the first entry.");
    const previous = units[index - 1];
    if (
      previous &&
      (unit.section_position < previous.section_position ||
        (unit.section_position === previous.section_position &&
          unit.character_offset <= previous.character_offset))
    ) {
      throw new Error(
        "Selected entries must have different locations in reading order. Ignore an entry or use manual review.",
      );
    }
  }
  return units;
}
