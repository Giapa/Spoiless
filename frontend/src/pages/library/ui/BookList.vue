<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue";
import { z } from "zod";
import BookQuestion from "./BookQuestion.vue";
import ConversationHistory from "./ConversationHistory.vue";
import type { Book } from "../api/libraryApi";
import ReadingProgress from "./ReadingProgress.vue";

const props = defineProps<{ book?: Book; loading: boolean; busy: boolean; model: string }>();
const emit = defineEmits<{ delete: [book: Book]; chaptersAnalyzed: [] }>();
const searchAvailable = ref(false);
const historyVersion = ref(0);
const analyzing = ref(false);
const analysisError = ref("");
let analysisRequest: AbortController | null = null;

async function analyzeChapters() {
  if (!props.book || !props.model || analyzing.value) return;
  const controller = new AbortController();
  analysisRequest = controller;
  analyzing.value = true;
  analysisError.value = "";
  try {
    const response = await fetch(
      `/api/books/${encodeURIComponent(props.book.id)}/analyze-chapters`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Spoiless-Action": "1" },
        body: JSON.stringify({ model: props.model, confirm: true }),
        signal: controller.signal,
      },
    );
    if (!response.ok) {
      const detail = z
        .object({ detail: z.string() })
        .safeParse(await response.json().catch(() => null));
      throw new Error(
        detail.success ? detail.data.detail : "Could not analyze chapters. Please try again.",
      );
    }
    if (analysisRequest === controller) emit("chaptersAnalyzed");
  } catch (error) {
    if (analysisRequest === controller)
      analysisError.value =
        error instanceof Error ? error.message : "Could not analyze chapters. Please try again.";
  } finally {
    if (analysisRequest === controller) {
      analysisRequest = null;
      analyzing.value = false;
    }
  }
}
onBeforeUnmount(() => {
  analysisRequest?.abort();
  analysisRequest = null;
});
</script>

<template>
  <section class="chat" aria-label="Book conversation">
    <p v-if="loading" role="status">Loading your library…</p>
    <div v-else-if="!book" class="empty">
      <h2>Start with a book</h2>
      <p>Add an EPUB to ask questions about what you have read.</p>
    </div>
    <template v-else>
      <header class="chat-header">
        <div>
          <p class="eyebrow">YOUR BOOK</p>
          <h2>{{ book.title }}</h2>
        </div>
        <button
          class="delete"
          type="button"
          :disabled="busy"
          :aria-label="`Delete ${book.title}`"
          @click="$emit('delete', book)"
        >
          Delete book
        </button>
      </header>
      <div v-if="!book.chapters_confirmed" class="unavailable">
        <h3>Chapters could not be detected</h3>
        <p>
          Analyze the book for chapter boundaries. Short passages around uncertain boundaries,
          including unread text, may be sent to OpenAI. Detection can miss chapters, including
          unmarked boundaries, and may expose unread text.
        </p>
        <p v-if="!model">Connect an account and choose a model in Account and model first.</p>
        <button type="button" :disabled="!model || analyzing" @click="analyzeChapters">
          {{ analyzing ? "Analyzing chapters…" : "Analyze chapters" }}
        </button>
        <p v-if="analyzing" role="status">Analyzing chapter boundaries…</p>
        <p v-if="analysisError" role="alert">{{ analysisError }}</p>
      </div>
      <template v-else>
        <div class="reading">
          <ReadingProgress
            :book-id="book.id"
            @availability="searchAvailable = $event"
            @changed="historyVersion++"
          />
        </div>
        <div v-if="searchAvailable" class="conversation">
          <ConversationHistory :book-id="book.id" :version="historyVersion" />
          <BookQuestion :book-id="book.id" :model="model" @saved="historyVersion++" />
        </div>
        <div v-else class="conversation">
          <div class="empty">
            <h3>Choose your current chapter</h3>
            <p>
              Save your reading progress to chat about completed chapters. Your current chapter
              stays unread.
            </p>
          </div>
          <BookQuestion :book-id="book.id" :model="model" disabled />
        </div>
      </template>
    </template>
  </section>
</template>

<style scoped>
.chat {
  min-width: 0;
  padding: 32px clamp(20px, 5vw, 72px) 48px;
}
.chat-header {
  display: flex;
  gap: 20px;
  align-items: start;
  justify-content: space-between;
  border-bottom: 1px solid #e3e7e1;
  padding-bottom: 20px;
}
.chat-header > div {
  min-width: 0;
}
h2,
h3,
p {
  margin: 0;
}
h2 {
  font-size: 24px;
  overflow-wrap: anywhere;
}
h3 {
  font-size: 19px;
}
.eyebrow {
  font-size: 11px;
  letter-spacing: 0.1em;
  font-weight: 700;
  color: #617465;
  margin-bottom: 6px;
}
.delete {
  flex-shrink: 0;
  background: transparent;
  border: 0;
  color: #59675d;
  font: inherit;
  min-height: 44px;
  cursor: pointer;
}
.delete:hover {
  color: #9c2929;
}
.reading,
.conversation {
  max-width: 800px;
  margin: 0 auto;
}
.reading {
  padding: 8px 0 18px;
  border-bottom: 1px solid #e3e7e1;
}
.empty,
.unavailable {
  max-width: 520px;
  margin: 80px auto;
  text-align: center;
}
.empty p,
.unavailable p {
  margin-top: 10px;
  color: #5e6b61;
  line-height: 1.6;
}
.unavailable button {
  margin-top: 16px;
  padding: 8px 16px;
  min-height: 44px;
  border: 1px solid #315b45;
  border-radius: 6px;
  color: white;
  background: #315b45;
  font: inherit;
  cursor: pointer;
}
.unavailable button:disabled {
  opacity: 0.55;
  cursor: default;
}
@media (max-width: 700px) {
  .chat {
    padding: 24px 16px 40px;
  }
  .conversation {
    display: flex;
    flex-direction: column;
  }
  .conversation :deep(.question) {
    order: -1;
  }
  h2 {
    font-size: 21px;
  }
  .empty,
  .unavailable {
    margin: 48px auto;
  }
}
</style>
