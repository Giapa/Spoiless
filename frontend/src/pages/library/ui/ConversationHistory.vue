<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { z } from "zod";

const props = defineProps<{ bookId: string; version: number }>();
const schema = z.array(
  z.object({
    question: z.string(),
    answer: z.string(),
    citations: z.array(
      z.object({
        section_position: z.number().int().nonnegative(),
        character_offset: z.number().int().nonnegative(),
        quote: z.string(),
      }),
    ),
  }),
);
const turns = ref<z.infer<typeof schema>>([]);
const loading = ref(false);
const error = ref("");
let request: AbortController | null = null;

function clear() {
  request?.abort();
  request = null;
  turns.value = [];
  error.value = "";
  loading.value = false;
}
async function load() {
  clear();
  const controller = new AbortController();
  request = controller;
  loading.value = true;
  try {
    const response = await fetch(`/api/books/${encodeURIComponent(props.bookId)}/conversation`, {
      signal: controller.signal,
      cache: "no-store",
    });
    if (!response.ok) throw new Error();
    const result = schema.parse(await response.json());
    if (request === controller) turns.value = result;
  } catch {
    if (request === controller) error.value = "Could not load conversation history.";
  } finally {
    if (request === controller) {
      request = null;
      loading.value = false;
    }
  }
}
watch(
  () => props.version,
  () => void load(),
);
onMounted(() => {
  void load();
});
onBeforeUnmount(() => {
  clear();
});
</script>

<template>
  <section class="history" aria-label="Conversation history">
    <h3>Conversation</h3>
    <p>
      Questions and answers are stored on this device. Recent turns may be sent to OpenAI with new
      questions. Changing chapters starts a new conversation.
    </p>
    <p v-if="loading" role="status">Loading conversation…</p>
    <p v-else-if="error" role="alert">
      {{ error }} <button type="button" @click="load">Retry</button>
    </p>
    <p v-else-if="!turns.length">No questions in this conversation yet.</p>
    <ol v-else class="turns">
      <li v-for="(turn, index) in turns" :key="index">
        <p class="question">{{ turn.question }}</p>
        <p class="answer">{{ turn.answer }}</p>
        <ul v-if="turn.citations.length" aria-label="Citations">
          <li v-for="(citation, citationIndex) in turn.citations" :key="citationIndex">
            <p>
              Section {{ citation.section_position + 1 }} · character
              {{ citation.character_offset + 1 }}
            </p>
            <blockquote>{{ citation.quote }}</blockquote>
          </li>
        </ul>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.history {
  margin-top: 12px;
  max-width: 800px;
  min-height: 100px;
}
h3 {
  font-size: 15px;
  margin: 24px 0 10px;
}
p {
  font-size: 14px;
  margin: 6px 0;
  color: #555;
}
.turns {
  list-style: none;
  margin: 12px 0;
  padding: 0;
}
.turns > li {
  border-top: 1px solid #e3e7e1;
  padding: 16px 0;
}
.question {
  font-weight: 600;
}
.question,
.answer,
blockquote {
  color: #1b1b1b;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
blockquote {
  margin: 6px 0;
}
button {
  font: inherit;
  min-height: 44px;
  padding: 8px 12px;
  border: 1px solid #aaa;
  border-radius: 6px;
  background: white;
}
</style>
