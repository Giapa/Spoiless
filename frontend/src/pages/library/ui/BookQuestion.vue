<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { z } from "zod";

const props = defineProps<{ bookId: string; model: string; disabled?: boolean }>();
const emit = defineEmits<{ saved: [] }>();
const question = ref("");
const busy = ref(false);
const error = ref("");
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
}
async function ask() {
  if (props.disabled) return;
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
    schema.parse(await response.json());
    if (request === controller) {
      question.value = "";
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
  <section class="question" aria-label="Ask about completed chapters">
    <form @submit.prevent="ask">
      <label :for="`question-${bookId}`">Your question</label>
      <textarea
        :id="`question-${bookId}`"
        v-model="question"
        maxlength="500"
        :disabled="disabled"
        required
        @input="clear"
      />
      <p>
        Your question, relevant completed passages and recent conversation may be sent to OpenAI.
        Questions and answers are saved on this device. AI answers may contain spoilers.
      </p>
      <p v-if="model">
        Using ChatGPT plan ·
        <a href="https://chatgpt.com/settings/usage" target="_blank" rel="noopener noreferrer"
          >Manage usage</a
        >
      </p>
      <p v-if="disabled">Save progress beyond the first chapter to start a conversation.</p>
      <p v-if="!model">Choose a model in Account and model to ask a question.</p>
      <button type="submit" :disabled="disabled || busy || !model || !question.trim()">
        {{ busy ? "Asking…" : "Ask" }}
      </button>
    </form>
    <p v-if="busy" role="status">Checking the completed chapters…</p>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.question {
  margin-top: 20px;
  max-width: 800px;
  padding: 18px;
  border: 1px solid #ccd6cc;
  border-radius: 16px;
  background: white;
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
  justify-self: end;
  color: white;
  background: #315b45;
  border-color: #315b45;
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
