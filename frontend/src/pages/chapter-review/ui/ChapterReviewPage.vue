<script setup lang="ts">
import { useChapterReview } from "../model/useChapterReview";
import { ref } from "vue";
import NavigationReview from "./NavigationReview.vue";
import SectionReview from "./SectionReview.vue";

const props = defineProps<{ book: { id: string; title: string } }>();
const emit = defineEmits<{ back: [] }>();
const suggestionsDirty = ref(false);
const suggestionsSaving = ref(false);
const {
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
} = useChapterReview(props.book.id, () => emit("back"));

function goBack() {
  if (
    (!dirty.value && !suggestionsDirty.value) ||
    window.confirm("Leave without saving your changes?")
  )
    emit("back");
}

async function revealManually() {
  if (suggestionsDirty.value && !window.confirm("Discard your unsaved table-of-contents choices?"))
    return;
  await reveal();
  if (revealed.value) suggestionsDirty.value = false;
}
</script>

<template>
  <main>
    <button class="back" type="button" :disabled="saving || suggestionsSaving" @click="goBack">
      ← Back to library
    </button>
    <h1>Review chapters</h1>
    <p class="book-title">{{ book.title }}</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <NavigationReview
      v-if="!revealed"
      :book-id="book.id"
      :disabled="loading"
      @saved="emit('back')"
      @dirty="suggestionsDirty = $event"
      @busy="suggestionsSaving = $event"
    />
    <section v-if="!revealed" class="panel" aria-labelledby="warning-title">
      <h2 id="warning-title">This may reveal spoilers</h2>
      <p>
        Reviewing chapter boundaries shows the full text of the book, including chapters you have
        not read.
      </p>
      <p>
        Use manual review if the table of contents is missing or incorrect. You must mark and verify
        every chapter before saving.
      </p>
      <button
        class="primary"
        type="button"
        :disabled="loading || suggestionsSaving"
        @click="revealManually"
      >
        {{ loading ? "Loading…" : "Show book text" }}
      </button>
    </section>

    <template v-else>
      <section class="panel" aria-labelledby="instructions-title">
        <h2 id="instructions-title">Mark every chapter</h2>
        <p>
          The beginning of the book is marked for you. If it contains front matter, select the
          option below, then mark the start of Chapter 1.
        </p>
        <p>
          For each later chapter, place the cursor immediately before its first character in the
          section text and select “Mark chapter start at cursor”. You may need to scroll inside a
          section.
        </p>
        <label class="check"
          ><input
            type="checkbox"
            :checked="units[0]?.kind === 'front_matter'"
            @change="setFrontMatter(($event.target as HTMLInputElement).checked)"
          />
          The book begins with front matter</label
        >
      </section>

      <section class="panel" aria-labelledby="boundaries-title">
        <h2 id="boundaries-title">Marked starts</h2>
        <p>Starts are listed in reading order. Character positions count from zero.</p>
        <ol class="unit-list">
          <li
            v-for="(unit, index) in units"
            :key="`${unit.section_position}-${unit.character_offset}`"
          >
            <span
              >{{
                unit.kind === "front_matter"
                  ? "Front matter"
                  : `Chapter ${index + (units[0]?.kind === "front_matter" ? 0 : 1)}`
              }}
              · Section {{ unit.section_position + 1 }}, character {{ unit.character_offset }}</span
            >
            <button v-if="index > 0" class="remove" type="button" @click="removeStart(index)">
              Remove
            </button>
          </li>
        </ol>
        <label class="check"
          ><input v-model="acknowledged" type="checkbox" /> I have marked and verified every chapter
          start.</label
        >
        <button class="primary" type="button" :disabled="!acknowledged || saving" @click="save">
          {{ saving ? "Saving…" : "Save chapter boundaries" }}
        </button>
      </section>

      <section class="panel" aria-labelledby="text-title">
        <h2 id="text-title">Book text</h2>
        <p>This text includes unread material. Select the start of each chapter carefully.</p>
        <SectionReview
          v-for="section in sections"
          :key="section.position"
          :section="section"
          @mark="addStart"
        />
      </section>
    </template>
  </main>
</template>

<style scoped>
main {
  max-width: 1064px;
  margin: 40px auto;
  padding: 0 24px;
}
h1,
h2,
p {
  margin: 0;
}
h1 {
  font-size: 30px;
  line-height: 1.2;
  margin-top: 24px;
}
h2 {
  font-size: 19px;
}
.book-title {
  color: #555;
  margin-top: 6px;
  overflow-wrap: anywhere;
}
.panel {
  background: #fff;
  border: 1px solid #e2e2e2;
  border-radius: 8px;
  margin-top: 24px;
  padding: 24px;
}
.panel p {
  line-height: 1.55;
  margin-top: 12px;
}
button {
  min-height: 44px;
  padding: 10px 16px;
  border-radius: 6px;
}
.back,
.remove {
  border: 0;
  background: transparent;
  text-decoration: underline;
  padding-left: 0;
}
.primary {
  background: #171717;
  color: #fff;
  border: 0;
  margin-top: 20px;
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
.unit-list {
  margin: 16px 0 0;
  padding-left: 24px;
}
.unit-list li {
  padding: 4px 0;
}
.remove {
  margin-left: 16px;
}
.error {
  margin-top: 20px;
  padding: 12px;
  border-left: 3px solid #ac2525;
  background: #fff;
}
@media (max-width: 600px) {
  main {
    margin: 28px auto;
    padding: 0 16px;
  }
  h1 {
    font-size: 24px;
  }
  .panel {
    padding: 16px;
  }
}
</style>
