<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { z } from "zod";

const props = defineProps<{ bookId: string; model: string }>();
const emit = defineEmits<{ saved: [] }>();
const question = ref("");
const busy = ref(false);
const error = ref("");
const answer = ref<{
  answer: string;
  citations: { section_position: number; character_offset: number; quote: string }[];
} | null>(null);
const schema = z.object({
  answer: z.string(),
  citations: z.array(
    z.object({
      section_position: z.number().int().nonnegative(),
      character_offset: z.number().int().nonnegative(),
      quote: z.string(),
    }),
  ),
});
let request: AbortController | null = null;

function clear() {
  request?.abort();
  request = null;
  busy.value = false;
  error.value = "";
  answer.value = null;
}
async function ask() {
  clear();
  const controller = new AbortController();
  request = controller;
  busy.value = true;
  try {
    const response = await fetch(`/api/books/${encodeURIComponent(props.bookId)}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Spoiless-Action": "1" },
      body: JSON.stringify({ question: question.value, model: props.model, confirm: true }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      const limit = z
        .object({
          detail: z.object({ code: z.literal("subscription_sharing_usage_limit_exceeded") }),
        })
        .safeParse(body);
      if (response.status === 429 && limit.success)
        throw new Error("ChatGPT usage limit reached. Review your usage in ChatGPT settings.");
      const detail = z.object({ detail: z.string() }).safeParse(body);
      if ([409, 422, 502].includes(response.status) && detail.success)
        throw new Error(detail.data.detail);
      throw new Error("Could not answer the question. Please try again.");
    }
    const result = schema.parse(await response.json());
    if (request === controller) {
      answer.value = result;
      emit("saved");
    }
  } catch (cause) {
    if (request === controller)
      error.value =
        cause instanceof Error ? cause.message : "Could not answer the question. Please try again.";
  } finally {
    if (request === controller) {
      request = null;
      busy.value = false;
    }
  }
}
watch(() => props.model, clear);
onMounted(() => window.addEventListener("blur", clear));
onBeforeUnmount(() => {
  window.removeEventListener("blur", clear);
  clear();
});
</script>

<template>
  <details class="question" @toggle="clear">
    <summary>Ask about completed chapters</summary>
    <form @submit.prevent="ask">
      <p>
        Your question and relevant passages from completed chapters are sent to OpenAI. Recent
        questions and answers may also be sent to OpenAI. AI answers may contain spoilers.
      </p>
      <p>
        Questions and answers are saved on this device. The displayed answer clears when you leave
        this window.
      </p>
      <p v-if="model">
        Using ChatGPT plan ·
        <a href="https://chatgpt.com/settings/usage" target="_blank" rel="noopener noreferrer"
          >Manage usage</a
        >
      </p>
      <label :for="`question-${bookId}`">Your question</label>
      <textarea
        :id="`question-${bookId}`"
        v-model="question"
        maxlength="500"
        required
        @input="clear"
      />
      <p v-if="!model">Choose a ChatGPT model below to ask a question.</p>
      <button type="submit" :disabled="busy || !model || !question.trim()">
        {{ busy ? "Asking…" : "Ask" }}
      </button>
    </form>
    <p v-if="busy" role="status">Checking the completed chapters…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <div v-if="answer" aria-label="Answer">
      <p class="answer">{{ answer.answer }}</p>
      <ol v-if="answer.citations.length" aria-label="Citations">
        <li
          v-for="citation in answer.citations"
          :key="`${citation.section_position}-${citation.character_offset}`"
        >
          <p>
            Section {{ citation.section_position + 1 }} · character
            {{ citation.character_offset + 1 }}
          </p>
          <blockquote>{{ citation.quote }}</blockquote>
        </li>
      </ol>
    </div>
  </details>
</template>

<style scoped>
.question {
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
textarea,
button {
  font: inherit;
  min-height: 44px;
  padding: 8px 12px;
  border: 1px solid #aaa;
  border-radius: 6px;
  background: white;
}
textarea {
  min-height: 88px;
  resize: vertical;
}
button {
  justify-self: start;
}
p {
  font-size: 14px;
  margin: 6px 0;
  color: #555;
}
.answer,
blockquote {
  color: #1b1b1b;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
blockquote {
  margin: 6px 0;
}
</style>
