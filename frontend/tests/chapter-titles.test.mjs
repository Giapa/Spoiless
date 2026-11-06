import assert from "node:assert/strict";
import test from "node:test";
import { chapterTitles } from "../src/pages/library/model/chapterTitles.ts";

test("shows titles matched to chapter starts and falls back for missing titles", () => {
  const units = [
    { kind: "front_matter", section_position: 0, character_offset: 0 },
    { kind: "chapter", section_position: 1, character_offset: 0 },
    { kind: "chapter", section_position: 1, character_offset: 12 },
    { kind: "chapter", section_position: 2, character_offset: 0 },
  ];
  const entries = [
    { title: "Contents", section_position: 0, character_offset: 0 },
    { title: " The Lost Key ", section_position: 1, character_offset: 0 },
    { title: "  ", section_position: 1, character_offset: 12 },
    { title: "Chapter 3", section_position: 2, character_offset: 0 },
  ];
  assert.deepEqual(chapterTitles(units, entries), ["Chapter 1: The Lost Key", "Chapter 2", "Chapter 3"]);
});
