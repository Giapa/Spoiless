<script setup lang="ts">
import { onMounted, ref } from "vue";
import { z } from "zod";

const props = defineProps<{ bookId: string }>();
const schema = z.object({
  chapter_count: z.number().int().nonnegative(),
  current_chapter: z.number().int().nullable(),
});
const progress = ref<z.infer<typeof schema> | null>(null);
const choice = ref("");
const busy = ref(false);
const error = ref("");
const notice = ref("");
const endpoint = `/api/books/${encodeURIComponent(props.bookId)}/progress`;

async function load() {
  error.value = "";
  try {
    const response = await fetch(endpoint);
    if (!response.ok) throw new Error();
    progress.value = schema.parse(await response.json());
    choice.value = progress.value.current_chapter?.toString() ?? "";
  } catch {
    error.value = "Could not load reading progress.";
  }
}
async function save() {
  if (!choice.value) return;
  busy.value = true;
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
  } catch {
    error.value = "Could not save reading progress. Try again.";
  } finally {
    busy.value = false;
  }
}
onMounted(load);
</script>

<template>
  <div class="progress">
    <p v-if="error" role="alert">{{ error }} <button type="button" @click="load">Retry</button></p>
    <form v-if="progress && progress.chapter_count" @submit.prevent="save">
      <label :for="`progress-${bookId}`">Current chapter</label>
      <div class="controls">
        <select :id="`progress-${bookId}`" v-model="choice" :disabled="busy">
          <option value="" disabled>Choose progress</option>
          <option
            v-for="chapter in Math.max(0, progress.chapter_count - 1)"
            :key="chapter"
            :value="String(chapter + 1)"
          >
            Chapter {{ chapter + 1 }}
          </option>
          <option :value="String(progress.chapter_count + 1)">Finished book</option>
        </select>
        <button
          type="submit"
          :disabled="busy || !choice || Number(choice) === progress.current_chapter"
        >
          Save
        </button>
      </div>
      <p>The current chapter is treated as unread.</p>
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
