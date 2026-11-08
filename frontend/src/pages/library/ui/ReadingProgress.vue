<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { z } from "zod";
import { chapterTitles } from "../model/chapterTitles";

const props = defineProps<{ bookId: string }>();
const emit = defineEmits<{ availability: [ready: boolean]; changed: [] }>();
const schema = z.object({
  chapter_count: z.number().int().nonnegative(),
  current_chapter: z.number().int().nullable(),
});
const progress = ref<z.infer<typeof schema> | null>(null);
const chapters = ref<string[]>([]);
const titlesUnavailable = ref(false);
const choice = ref("");
const busy = ref(false);
const loading = ref(false);
let loadVersion = 0;
const error = ref("");
const notice = ref("");
const endpoint = `/api/books/${encodeURIComponent(props.bookId)}/progress`;
const bookEndpoint = `/api/books/${encodeURIComponent(props.bookId)}`;

async function loadChapterTitles() {
  const location = z.object({
    section_position: z.number().int().nonnegative().nullable(),
    character_offset: z.number().int().nonnegative().nullable(),
  });
  const [unitsResponse, navigationResponse] = await Promise.all([
    fetch(`${bookEndpoint}/reading-units`),
    fetch(`${bookEndpoint}/navigation?include_titles=true`),
  ]);
  if (!unitsResponse.ok || !navigationResponse.ok) throw new Error();
  const units = z
    .array(location.extend({ kind: z.enum(["front_matter", "chapter"]) }))
    .parse(await unitsResponse.json());
  const entries = z
    .array(location.extend({ title: z.string().nullable() }))
    .parse(await navigationResponse.json());
  return chapterTitles(units, entries);
}

async function load() {
  const version = ++loadVersion;
  loading.value = true;
  error.value = "";
  notice.value = "";
  try {
    const [response, titles] = await Promise.all([
      fetch(endpoint),
      loadChapterTitles().catch(() => null),
    ]);
    if (!response.ok) throw new Error();
    const updated = schema.parse(await response.json());
    if (version !== loadVersion) return;
    if (progress.value && progress.value.current_chapter !== updated.current_chapter)
      emit("changed");
    progress.value = updated;
    chapters.value = titles ?? [];
    titlesUnavailable.value = titles === null;
    choice.value = progress.value.current_chapter?.toString() ?? "";
    emit("availability", (progress.value.current_chapter ?? 0) > 1);
  } catch {
    if (version !== loadVersion) return;
    emit("availability", false);
    error.value = "Could not load reading progress.";
  } finally {
    if (version === loadVersion) loading.value = false;
  }
}
async function save() {
  if (!choice.value || Number(choice.value) === progress.value?.current_chapter) return;
  ++loadVersion;
  loading.value = false;
  busy.value = true;
  emit("availability", false);
  error.value = "";
  notice.value = "";
  try {
    const response = await fetch(endpoint, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_chapter: Number(choice.value) }),
    });
    if (!response.ok) throw new Error();
    progress.value = schema.parse(await response.json());
    notice.value = "Reading progress saved.";
    emit("availability", (progress.value.current_chapter ?? 0) > 1);
  } catch {
    await load();
    error.value = "Could not save reading progress. Check the selection and try again.";
  } finally {
    busy.value = false;
  }
}
function refresh() {
  if (!busy.value) void load();
}
onMounted(() => {
  void load();
  window.addEventListener("focus", refresh);
});
onBeforeUnmount(() => {
  ++loadVersion;
  window.removeEventListener("focus", refresh);
});
</script>

<template>
  <div class="progress">
    <p v-if="error" role="alert">{{ error }} <button type="button" @click="load">Retry</button></p>
    <div v-if="progress && progress.chapter_count">
      <label :for="`progress-${bookId}`">Current chapter</label>
      <div class="controls">
        <select
          :id="`progress-${bookId}`"
          v-model="choice"
          :disabled="busy || loading"
          @change="save"
        >
          <option value="" disabled>Choose progress</option>
          <option v-for="chapter in progress.chapter_count" :key="chapter" :value="String(chapter)">
            {{ chapters[chapter - 1] || `Chapter ${chapter}` }}
          </option>
          <option :value="String(progress.chapter_count + 1)">Finished book</option>
        </select>
      </div>
      <p>The current chapter is treated as unread.</p>
      <p v-if="titlesUnavailable" role="status">
        Chapter titles could not be loaded. <button type="button" @click="load">Retry</button>
      </p>
      <p>
        Automatic detection can miss or misidentify chapter boundaries, which could expose unread
        text. Check the source EPUB before relying on this selection.
      </p>
      <p v-if="notice" role="status">{{ notice }}</p>
    </div>
  </div>
</template>

<style scoped>
.progress {
  margin-top: 12px;
}
label {
  display: block;
  font-size: 14px;
  font-weight: 600;
}
.controls {
  display: flex;
  gap: 8px;
  margin-top: 6px;
  flex-wrap: wrap;
}
select {
  flex: 1 1 220px;
}
select,
button {
  font: inherit;
  min-height: 44px;
  padding: 8px 12px;
  border: 1px solid #aaa;
  border-radius: 6px;
  background: white;
}
button {
  cursor: pointer;
}
button:disabled {
  opacity: 0.55;
  cursor: default;
}
p {
  margin: 6px 0 0;
  color: #555;
  font-size: 14px;
  line-height: 1.5;
}
</style>
