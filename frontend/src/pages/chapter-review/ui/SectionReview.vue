<script setup lang="ts">
import { ref } from "vue";
import type { BookSection } from "../api/chapterReviewApi";

const props = defineProps<{ section: BookSection }>();
const emit = defineEmits<{ mark: [section: BookSection, offset: number] }>();
const textArea = ref<HTMLTextAreaElement | null>(null);

function mark() {
  const cursor = textArea.value?.selectionStart ?? 0;
  // Browser selection offsets are UTF-16; the backend stores Unicode code points.
  let offset = cursor;
  if (offset > 0 && offset < props.section.text.length) {
    const previous = props.section.text.charCodeAt(offset - 1);
    const current = props.section.text.charCodeAt(offset);
    if (previous >= 0xd800 && previous <= 0xdbff && current >= 0xdc00 && current <= 0xdfff)
      offset--;
  }
  emit("mark", props.section, Array.from(props.section.text.slice(0, offset)).length);
}
</script>

<template>
  <section class="section">
    <label :for="`section-${section.position}`">Section {{ section.position + 1 }}</label>
    <textarea
      :id="`section-${section.position}`"
      ref="textArea"
      :value="section.text"
      readonly
      rows="9"
      spellcheck="false"
    />
    <button type="button" @click="mark">Mark chapter start at cursor</button>
  </section>
</template>

<style scoped>
.section {
  padding: 20px 0;
  border-top: 1px solid #e6e6e6;
}
label {
  display: block;
  font-weight: 600;
  margin-bottom: 8px;
}
textarea {
  width: 100%;
  resize: vertical;
  font: inherit;
  line-height: 1.55;
  padding: 12px;
  border: 1px solid #aaa;
  border-radius: 6px;
  background: #fff;
  color: #1b1b1b;
}
button {
  margin-top: 8px;
  border: 1px solid #999;
  border-radius: 6px;
  background: #fff;
  padding: 10px 14px;
  min-height: 44px;
}
</style>
