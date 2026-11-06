<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { z } from "zod";

const props = defineProps<{ bookId: string }>();
const emit = defineEmits<{ availability: [ready: boolean]; completed: [count: number] }>();
const schema = z.object({
  chapter_count: z.number().int().nonnegative(),
  current_chapter: z.number().int().nullable(),
});
const progress = ref<z.infer<typeof schema> | null>(null);
const choice = ref("");
const busy = ref(false);
const loading = ref(false);
let loadVersion = 0;
const error = ref("");
const notice = ref("");
const endpoint = `/api/books/${encodeURIComponent(props.bookId)}/progress`;

async function load() {
  const version = ++loadVersion;
  loading.value = true;
  emit("availability", false);
  error.value = "";
  notice.value = "";
  try {
    const response = await fetch(endpoint);
    if (!response.ok) throw new Error();
    const updated = schema.parse(await response.json());
    if (version !== loadVersion) return;
    progress.value = updated;
    choice.value = progress.value.current_chapter?.toString() ?? "";
    emit("completed", Math.max(0, (progress.value.current_chapter ?? 1) - 1));
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
  if (!choice.value) return;
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
    emit("completed", Math.max(0, (progress.value.current_chapter ?? 1) - 1));
    emit("availability", (progress.value.current_chapter ?? 0) > 1);
  } catch {
    error.value = "Could not save reading progress. Try again.";
  } finally {
    busy.value = false;
  }
}
function changeChoice() {
  notice.value = "";
  emit(
    "availability",
    Number(choice.value) > 1 && Number(choice.value) === progress.value?.current_chapter,
  );
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
    <form v-if="progress && progress.chapter_count" @submit.prevent="save">
      <label :for="`progress-${bookId}`">Current chapter</label>
      <div class="controls">
        <select
          :id="`progress-${bookId}`"
          v-model="choice"
          :disabled="busy || loading"
          @change="changeChoice"
        >
          <option value="" disabled>Choose progress</option>
          <option v-for="chapter in progress.chapter_count" :key="chapter" :value="String(chapter)">
            Chapter {{ chapter }}
          </option>
          <option :value="String(progress.chapter_count + 1)">Finished book</option>
        </select>
        <button
          type="submit"
          :disabled="busy || loading || !choice || Number(choice) === progress.current_chapter"
        >
          Save
        </button>
      </div>
      <p>The current chapter is treated as unread.</p>
      <p>
        Automatic detection can miss or misidentify chapter boundaries, which could expose unread
        text. Check the source EPUB before relying on this selection.
      </p>
      <p v-if="notice" role="status">{{ notice }}</p>
    </form>
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
}
</style>
