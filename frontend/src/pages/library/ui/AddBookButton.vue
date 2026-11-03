<script setup lang="ts">
import { ref } from "vue";

defineProps<{ disabled: boolean; busy: boolean }>();
const emit = defineEmits<{ select: [file: File] }>();
const input = ref<HTMLInputElement | null>(null);

function selectFile(event: Event) {
  const field = event.target as HTMLInputElement;
  const file = field.files?.[0];
  if (file) emit("select", file);
  field.value = "";
}
</script>

<template>
  <button class="primary" type="button" :disabled="disabled" @click="input?.click()">
    {{ busy ? "Working…" : "Add EPUB" }}
  </button>
  <input
    ref="input"
    type="file"
    accept=".epub,application/epub+zip"
    class="file-input"
    @change="selectFile"
  />
</template>

<style scoped>
.primary {
  color: white;
  background: #171717;
  white-space: nowrap;
  border: 0;
  border-radius: 6px;
  padding: 10px 16px;
  min-height: 44px;
}
.file-input {
  display: none;
}
</style>
