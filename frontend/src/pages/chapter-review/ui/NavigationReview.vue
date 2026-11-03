<script setup lang="ts">
import { onMounted, ref } from "vue";
import { loadNavigation, saveChapterReview, type NavigationEntry } from "../api/chapterReviewApi";
import { buildReadingUnits, type EntryChoice } from "../model/buildReadingUnits";

const props = defineProps<{ bookId: string; disabled: boolean }>();
const emit = defineEmits<{ saved: []; dirty: [value: boolean]; busy: [value: boolean] }>();
const entries = ref<NavigationEntry[]>([]);
const choices = ref<EntryChoice[]>([]);
const loading = ref(true);
const titlesLoading = ref(false);
const titlesVisible = ref(false);
const saving = ref(false);
const prefixIsFrontMatter = ref(false);
const acknowledged = ref(false);
const error = ref("");

async function load() {
  loading.value = true;
  error.value = "";
  try {
    entries.value = await loadNavigation(props.bookId);
    choices.value = entries.value.map(() => "");
  } catch {
    error.value = "Could not load the table of contents. Try again.";
  } finally {
    loading.value = false;
  }
}

function changed() {
  acknowledged.value = false;
  error.value = "";
  emit("dirty", true);
}

async function toggleTitles() {
  if (titlesVisible.value) {
    entries.value = entries.value.map((entry) => ({ ...entry, title: null }));
    titlesVisible.value = false;
    return;
  }
  titlesLoading.value = true;
  error.value = "";
  try {
    const withTitles = await loadNavigation(props.bookId, true);
    if (
      withTitles.length !== entries.value.length ||
      withTitles.some(
        (entry, index) =>
          entry.section_position !== entries.value[index]?.section_position ||
          entry.character_offset !== entries.value[index]?.character_offset,
      )
    ) {
      throw new Error("The table of contents changed. Return to the library and try again.");
    }
    entries.value = withTitles;
    titlesVisible.value = true;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "Could not show titles.";
  } finally {
    titlesLoading.value = false;
  }
}

async function save() {
  if (!acknowledged.value) return;
  error.value = "";
  try {
    const units = buildReadingUnits(entries.value, choices.value, prefixIsFrontMatter.value);
    saving.value = true;
    emit("busy", true);
    await saveChapterReview(props.bookId, units);
    emit("dirty", false);
    emit("saved");
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "Could not save chapter boundaries.";
  } finally {
    saving.value = false;
    emit("busy", false);
  }
}

onMounted(load);
</script>

<template>
  <section class="panel" aria-labelledby="suggestions-title">
    <h2 id="suggestions-title">Table of contents</h2>
    <p v-if="loading" role="status">Loading suggestions…</p>
    <template v-else-if="entries.length">
      <p>
        Choose what each entry represents. The table of contents may include entries that are not
        chapters. No book text is shown here.
      </p>
      <p>Titles can reveal story details. They are hidden until you choose to show them.</p>
      <p>
        Ignore only entries that are not chapters. If a chapter has no location, use manual review
        below.
      </p>
      <button
        type="button"
        class="secondary"
        :disabled="titlesLoading || saving || disabled"
        @click="toggleTitles"
      >
        {{
          titlesLoading
            ? "Loading…"
            : titlesVisible
              ? "Hide titles"
              : "Show titles (may reveal spoilers)"
        }}
      </button>
      <ol class="entries">
        <li v-for="(entry, index) in entries" :key="index">
          <div class="entry-heading">
            <span>{{
              titlesVisible ? entry.title || "Untitled entry" : `Entry ${index + 1}`
            }}</span>
            <span
              v-if="entry.section_position === null || entry.character_offset === null"
              class="location"
              >Location unavailable</span
            >
            <span v-else class="location"
              >Section {{ entry.section_position + 1 }}, character
              {{ entry.character_offset }}</span
            >
          </div>
          <label :for="`choice-${index}`">What is this entry?</label>
          <select
            :id="`choice-${index}`"
            v-model="choices[index]"
            :disabled="saving || disabled"
            @change="changed"
          >
            <option value="">Choose an option</option>
            <option
              value="chapter"
              :disabled="entry.section_position === null || entry.character_offset === null"
            >
              Chapter
            </option>
            <option
              value="front_matter"
              :disabled="entry.section_position === null || entry.character_offset === null"
            >
              Front matter
            </option>
            <option value="ignore">Ignore this entry</option>
          </select>
        </li>
      </ol>
      <label class="check"
        ><input
          v-model="prefixIsFrontMatter"
          type="checkbox"
          :disabled="saving || disabled"
          @change="changed"
        />
        Text before the first selected entry is front matter.</label
      >
      <p>Choose this only if the first selected entry starts after the beginning of the book.</p>
      <label class="check"
        ><input v-model="acknowledged" type="checkbox" :disabled="saving || disabled" /> I checked
        every entry and marked all chapters.</label
      >
      <p>Saving replaces any chapter boundaries you saved before.</p>
      <button
        type="button"
        class="primary"
        :disabled="!acknowledged || saving || disabled"
        @click="save"
      >
        {{ saving ? "Saving…" : "Save chapter boundaries" }}
      </button>
    </template>
    <p v-else-if="!error">
      No table of contents is available. You can use manual review below. For books uploaded before
      suggestions were added, upload the EPUB again to look for a table of contents.
    </p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <button
      v-if="error && !entries.length"
      type="button"
      class="secondary"
      :disabled="disabled"
      @click="load"
    >
      Try again
    </button>
  </section>
</template>

<style scoped>
.panel {
  background: #fff;
  border: 1px solid #e2e2e2;
  border-radius: 8px;
  margin-top: 24px;
  padding: 24px;
}
h2,
p {
  margin: 0;
}
h2 {
  font-size: 19px;
}
p {
  line-height: 1.55;
  margin-top: 12px;
}
button {
  min-height: 44px;
  padding: 10px 16px;
  border-radius: 6px;
}
.secondary {
  background: #fff;
  border: 1px solid #999;
  margin-top: 16px;
}
.primary {
  background: #171717;
  color: #fff;
  border: 0;
  margin-top: 20px;
}
.entries {
  margin: 20px 0 0;
  padding-left: 24px;
}
.entries li {
  padding: 16px 0;
  border-top: 1px solid #e6e6e6;
}
.entry-heading {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  overflow-wrap: anywhere;
}
.location {
  color: #555;
  font-size: 14px;
}
label:not(.check) {
  display: block;
  margin-top: 12px;
}
select {
  min-height: 44px;
  margin-top: 6px;
  max-width: 100%;
  padding: 8px;
  font: inherit;
}
.check {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-top: 20px;
}
.check input {
  margin-top: 5px;
}
.error {
  border-left: 3px solid #ac2525;
  padding-left: 12px;
}
@media (max-width: 600px) {
  .panel {
    padding: 16px;
  }
}
</style>
