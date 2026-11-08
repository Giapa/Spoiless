<script setup lang="ts">
import { apiFetch } from "../api/apiFetch";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { z } from "zod";

const props = defineProps<{ bookId: string; model: string; completed: number }>();
const chapter = ref("");
const mode = ref<"chapter" | "through">("chapter");
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
const recap = ref<z.infer<typeof schema> | null>(null);
let request: AbortController | null = null;

function clear() {
  request?.abort();
  request = null;
  busy.value = false;
  error.value = "";
  recap.value = null;
}
async function generate() {
  if (!props.model || !chapter.value) return;
  clear();
  const controller = new AbortController();
  request = controller;
  busy.value = true;
  try {
    const response = await apiFetch(`/api/books/${encodeURIComponent(props.bookId)}/recap`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Spoiless-Action": "1" },
      body: JSON.stringify({
        chapter: Number(chapter.value),
        mode: mode.value,
        model: props.model,
        confirm: true,
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
    if (request === controller) recap.value = result.data;
  } catch (cause) {
    if (request === controller)
      error.value =
        cause instanceof Error ? cause.message : "Could not create the recap. Please try again.";
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
  <details class="recap" @toggle="clear">
    <summary>Recap a completed chapter</summary>
    <form @submit.prevent="generate">
      <fieldset>
        <legend>Recap scope</legend>
        <label
          ><input
            v-model="mode"
            type="radio"
            :name="`recap-mode-${bookId}`"
            value="chapter"
            @change="clear"
          />
          Only this chapter</label
        >
        <label
          ><input
            v-model="mode"
            type="radio"
            :name="`recap-mode-${bookId}`"
            value="through"
            @change="clear"
          />
          From the beginning through this chapter</label
        >
      </fieldset>
      <p v-if="mode === 'chapter'">
        The selected chapter is sent to OpenAI. AI recaps may contain spoilers.
      </p>
      <p v-else>
        Confirmed front matter and all chapters through the selected chapter are sent to OpenAI. AI
        recaps may contain spoilers.
      </p>
      <p>
        Recaps are not saved and clear when you leave this window. Longer recaps use multiple AI
        requests, which may count toward your usage limits and may continue after you leave.
      </p>
      <p v-if="model">
        Using ChatGPT plan ·
        <a href="https://chatgpt.com/settings/usage" target="_blank" rel="noopener noreferrer"
          >Manage usage</a
        >
      </p>
      <label :for="`recap-chapter-${bookId}`">Chapter to recap</label>
      <select :id="`recap-chapter-${bookId}`" v-model="chapter" @change="clear">
        <option value="" disabled>Choose a chapter</option>
        <option v-for="number in completed" :key="number" :value="String(number)">
          Chapter {{ number }}
        </option>
      </select>
      <p v-if="!model">Choose a ChatGPT model below to create a recap.</p>
      <button type="submit" :disabled="busy || !model || !chapter">
        {{ busy ? "Creating recap…" : "Create recap" }}
      </button>
    </form>
    <p v-if="busy" role="status">Creating recap…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <section v-if="recap" aria-label="Recap">
      <p class="answer">{{ recap.answer }}</p>
      <ol v-if="recap.citations.length" aria-label="Citations">
        <li v-for="(citation, index) in recap.citations" :key="index">
          <p>
            Section {{ citation.section_position + 1 }} · character
            {{ citation.character_offset + 1 }}
          </p>
          <blockquote>{{ citation.quote }}</blockquote>
        </li>
      </ol>
    </section>
  </details>
</template>

<style scoped>
.recap {
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
fieldset {
  border: 0;
  padding: 0;
  margin: 0;
}
legend {
  font-size: 14px;
  font-weight: 600;
}
fieldset label {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 44px;
  font-weight: 400;
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
