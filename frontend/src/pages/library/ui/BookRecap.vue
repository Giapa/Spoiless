<script setup lang="ts">
import { apiFetch } from "../api/apiFetch";
import { onBeforeUnmount, ref, watch } from "vue";
import { z } from "zod";

const props = defineProps<{
  bookId: string;
  model: string;
  completed: number;
  current: number | null;
  disabled?: boolean;
}>();
const emit = defineEmits<{ saved: []; thinking: [question: string] }>();
const busy = ref(false);
const error = ref("");
const schema = z.object({
  answer: z.string(),
});
let request: AbortController | null = null;

function clear() {
  request?.abort();
  request = null;
  busy.value = false;
  error.value = "";
  emit("thinking", "");
}
async function generate(mode: "chapter" | "through") {
  if (
    props.disabled ||
    busy.value ||
    !props.model ||
    (mode === "chapter" ? !props.current : !props.completed)
  )
    return;
  clear();
  const controller = new AbortController();
  request = controller;
  busy.value = true;
  emit(
    "thinking",
    mode === "chapter"
      ? `Summarize chapter ${props.current}.`
      : `Summarize from the beginning before chapter ${props.completed + 1}.`,
  );
  try {
    const response = await apiFetch(`/api/books/${encodeURIComponent(props.bookId)}/recap`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Spoiless-Action": "1" },
      body: JSON.stringify({
        chapter: mode === "chapter" ? props.current : props.completed,
        mode,
        model: props.model,
        confirm: true,
        require_citations: false,
        include_current: mode === "chapter",
        save_turn: true,
      }),
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
      throw new Error("Could not create the recap. Please try again.");
    }
    const result = schema.safeParse(await response.json());
    if (!result.success) throw new Error("Could not verify the recap. Please try again.");
    if (request === controller) emit("saved");
  } catch (cause) {
    if (request === controller)
      error.value =
        cause instanceof Error ? cause.message : "Could not create the recap. Please try again.";
  } finally {
    if (request === controller) {
      request = null;
      busy.value = false;
      emit("thinking", "");
    }
  }
}
watch(() => props.model, clear);
watch(() => props.completed, clear);
watch(() => props.current, clear);
onBeforeUnmount(clear);
</script>

<template>
  <div class="recap">
    <div class="buttons">
      <button
        type="button"
        :disabled="disabled || busy || !model || !current"
        @click="generate('chapter')"
      >
        Summarize this chapter
      </button>
      <button
        type="button"
        :disabled="disabled || busy || !model || !completed"
        @click="generate('through')"
      >
        Summarize before current chapter
      </button>
    </div>
    <p>
      Summarizing this chapter includes unread text and may reveal spoilers. Text is sent to OpenAI.
    </p>
    <p v-if="error" role="alert">{{ error }}</p>
  </div>
</template>

<style scoped>
.recap {
  margin-top: 10px;
}
.buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
button {
  font: inherit;
  min-height: 44px;
  padding: 8px 12px;
  border: 1px solid #315b45;
  border-radius: 6px;
  color: white;
  background: #315b45;
  cursor: pointer;
}
button:disabled {
  opacity: 0.55;
  cursor: default;
}
p {
  font-size: 14px;
  margin: 8px 0;
}
.answer {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
