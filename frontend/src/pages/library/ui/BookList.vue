<script setup lang="ts">
import { ref } from "vue";
import PassageSearch from "./PassageSearch.vue";
import BookQuestion from "./BookQuestion.vue";
import ConversationHistory from "./ConversationHistory.vue";
import BookRecap from "./BookRecap.vue";
import type { Book } from "../api/libraryApi";
import ReadingProgress from "./ReadingProgress.vue";

defineProps<{ book?: Book; loading: boolean; busy: boolean; model: string }>();
defineEmits<{ delete: [book: Book] }>();
const searchAvailable = ref(false);
const historyVersion = ref(0);
const completedChapters = ref(0);
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
          Books imported before this update need to be imported again. If detection still fails,
          this book cannot be used for chapter-based search.
        </p>
      </div>
      <template v-else>
        <div class="reading">
          <ReadingProgress
            :book-id="book.id"
            @availability="searchAvailable = $event"
            @completed="completedChapters = $event"
          />
        </div>
        <div v-if="searchAvailable" class="conversation">
          <ConversationHistory :book-id="book.id" :version="historyVersion" />
          <BookQuestion :book-id="book.id" :model="model" @saved="historyVersion++" />
          <div class="tools">
            <PassageSearch :book-id="book.id" /><BookRecap
              :book-id="book.id"
              :model="model"
              :completed="completedChapters"
            />
          </div>
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
.tools {
  display: flex;
  flex-wrap: wrap;
  gap: 0 24px;
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
