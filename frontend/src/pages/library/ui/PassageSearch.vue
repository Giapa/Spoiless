<script setup lang="ts">
import { apiFetch } from "../api/apiFetch";
import { onBeforeUnmount, onMounted, ref } from "vue";
import { z } from "zod";

const props = defineProps<{ bookId: string }>();
const query = ref("");
const busy = ref(false);
const error = ref("");
const searched = ref(false);
const results = ref<{ section_position: number; character_offset: number; text: string }[]>([]);
const passageSchema = z.object({
  section_position: z.number().int().nonnegative(),
  character_offset: z.number().int().nonnegative(),
  text: z.string(),
});
let request: AbortController | null = null;

function clear() {
  request?.abort();
  request = null;
  busy.value = false;
  error.value = "";
  searched.value = false;
  results.value = [];
}
async function search() {
  clear();
  const controller = new AbortController();
  request = controller;
  busy.value = true;
  try {
    const response = await apiFetch(`/api/books/${encodeURIComponent(props.bookId)}/hybrid-search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query.value }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const body = z.object({ detail: z.string() }).safeParse(await response.json());
      throw new Error(body.success ? body.data.detail : "Search failed. Try again.");
    }
    const passages = z.array(passageSchema).parse(await response.json());
    if (request !== controller) return;
    results.value = passages;
    searched.value = true;
  } catch (cause) {
    if (request !== controller) return;
    error.value = cause instanceof Error ? cause.message : "Search failed. Try again.";
  } finally {
    if (request === controller) {
      request = null;
      busy.value = false;
    }
  }
}
onMounted(() => window.addEventListener("blur", clear));
onBeforeUnmount(() => {
  window.removeEventListener("blur", clear);
  clear();
});
</script>

<template>
  <details class="search" @toggle="clear">
    <summary>Search completed chapters</summary>
    <form @submit.prevent="search">
      <label :for="`query-${bookId}`">Search the book</label>
      <input
        :id="`query-${bookId}`"
        v-model="query"
        maxlength="500"
        required
        placeholder="Character, place, or detail"
        @input="clear"
      />
      <div class="controls">
        <button type="submit" :disabled="busy || !query.trim()">
          {{ busy ? "Searching…" : "Search" }}
        </button>
      </div>
      <p>Search uses words and meaning from completed chapters. It needs the local search model.</p>
    </form>
    <p v-if="busy" role="status">Searching completed chapters…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="searched && !results.length" role="status">No matching passages found.</p>
    <ol v-if="results.length" aria-label="Matching passages">
      <li
        v-for="passage in results"
        :key="`${passage.section_position}-${passage.character_offset}`"
      >
        <p class="source">
          Section {{ passage.section_position + 1 }} · character {{ passage.character_offset + 1 }}
        </p>
        <p class="passage">{{ passage.text }}</p>
      </li>
    </ol>
  </details>
</template>

<style scoped>
.search {
  margin-top: 12px;
  max-width: 620px;
}
summary {
  cursor: pointer;
  text-decoration: underline;
  min-height: 44px;
  padding: 10px 0;
}
form {
  display: grid;
  gap: 6px;
}
label {
  font-size: 14px;
  font-weight: 600;
}
input,
select,
button {
  font: inherit;
  min-height: 44px;
  padding: 8px 12px;
  border: 1px solid #aaa;
  border-radius: 6px;
  background: white;
}
.controls {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
button {
  cursor: pointer;
}
button:disabled {
  cursor: default;
  opacity: 0.55;
}
p {
  font-size: 14px;
  margin: 6px 0;
  color: #555;
}
ol {
  padding-left: 24px;
}
li {
  margin: 18px 0;
}
.source {
  font-weight: 600;
}
.passage {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: #1b1b1b;
}
</style>
