import { ref } from "vue";
import {
  loadChapterReview,
  saveChapterReview,
  type BookSection,
  type ReadingUnit,
} from "../api/chapterReviewApi";

export function useChapterReview(bookId: string, onSaved: () => void) {
  const sections = ref<BookSection[]>([]);
  const units = ref<ReadingUnit[]>([]);
  const revealed = ref(false);
  const loading = ref(false);
  const saving = ref(false);
  const dirty = ref(false);
  const acknowledged = ref(false);
  const error = ref("");

  async function reveal() {
    loading.value = true;
    error.value = "";
    try {
      const result = await loadChapterReview(bookId);
      sections.value = result.sections;
      units.value = result.units.length
        ? result.units
        : [{ kind: "chapter", section_position: 0, character_offset: 0 }];
      revealed.value = true;
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "Could not open chapter review.";
    } finally {
      loading.value = false;
    }
  }

  function addStart(section: BookSection, offset: number) {
    error.value = "";
    if (offset >= Array.from(section.text).length) {
      error.value = "Place the cursor before the first character of a chapter.";
      return;
    }
    if (
      units.value.some(
        (unit) => unit.section_position === section.position && unit.character_offset === offset,
      )
    ) {
      error.value = "A reading unit already starts at that position.";
      return;
    }
    units.value.push({
      kind: "chapter",
      section_position: section.position,
      character_offset: offset,
    });
    units.value.sort(
      (a, b) => a.section_position - b.section_position || a.character_offset - b.character_offset,
    );
    acknowledged.value = false;
    dirty.value = true;
  }

  function removeStart(index: number) {
    units.value.splice(index, 1);
    acknowledged.value = false;
    dirty.value = true;
  }

  function setFrontMatter(value: boolean) {
    const first = units.value[0];
    if (first) first.kind = value ? "front_matter" : "chapter";
    acknowledged.value = false;
    dirty.value = true;
  }

  async function save() {
    if (!acknowledged.value) return;
    if (!units.value.some((unit) => unit.kind === "chapter")) {
      error.value = "Mark at least one chapter before saving.";
      return;
    }
    saving.value = true;
    error.value = "";
    try {
      await saveChapterReview(bookId, units.value);
      dirty.value = false;
      onSaved();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "Could not save chapter boundaries.";
    } finally {
      saving.value = false;
    }
  }
  return {
    sections,
    units,
    revealed,
    loading,
    saving,
    dirty,
    acknowledged,
    error,
    reveal,
    addStart,
    removeStart,
    setFrontMatter,
    save,
  };
}
