import assert from "node:assert/strict";
import test from "node:test";
import { buildReadingUnits } from "../src/pages/chapter-review/model/buildReadingUnits.ts";

const entry = (section_position, character_offset) => ({
  title: null,
  section_position,
  character_offset,
});

test("uses only explicitly selected entries and preserves their order", () => {
  const entries = [entry(0, 0), entry(0, 8), entry(null, null), entry(1, 0)];
  const units = buildReadingUnits(entries, ["front_matter", "chapter", "ignore", "chapter"], false);
  assert.deepEqual(units, [
    { kind: "front_matter", section_position: 0, character_offset: 0 },
    { kind: "chapter", section_position: 0, character_offset: 8 },
    { kind: "chapter", section_position: 1, character_offset: 0 },
  ]);
});

test("requires an explicit front-matter choice when text precedes the first chapter", () => {
  const entries = [entry(0, 4)];
  assert.throws(() => buildReadingUnits(entries, ["chapter"], false), /front matter/);
  assert.deepEqual(buildReadingUnits(entries, ["chapter"], true), [
    { kind: "front_matter", section_position: 0, character_offset: 0 },
    { kind: "chapter", section_position: 0, character_offset: 4 },
  ]);
});

test("rejects unanswered, unresolved, duplicate and out-of-order entries", () => {
  assert.throws(() => buildReadingUnits([entry(0, 0)], [""], false));
  assert.throws(() => buildReadingUnits([entry(0, 0), entry(null, null)], ["chapter", "chapter"], false));
  assert.throws(() => buildReadingUnits([entry(0, 0), entry(0, 0)], ["chapter", "chapter"], false));
  assert.throws(() => buildReadingUnits([entry(1, 0), entry(0, 0)], ["chapter", "chapter"], true));
  assert.throws(() => buildReadingUnits([entry(0, 0)], ["front_matter"], false));
});
