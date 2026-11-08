<script setup lang="ts">
import { apiFetch } from "../api/apiFetch";
import { onMounted, onUnmounted, ref, watch } from "vue";
import { z } from "zod";

const props = defineProps<{ accountVersion: number }>();
const selectedModel = defineModel<string>({ required: true });
const models = ref<{ slug: string; display_name: string }[]>([]);
const busy = ref(false);
const loaded = ref(false);
const error = ref("");
let generation = 0;
let loadedAccountId: string | null = null;
function clearModels() {
  generation++;
  selectedModel.value = "";
  models.value = [];
  loaded.value = false;
  loadedAccountId = null;
  error.value = "";
  busy.value = false;
}
watch(() => props.accountVersion, clearModels);
const accountSchema = z.array(z.object({ id: z.string(), active: z.boolean() }));
async function activeAccountId(): Promise<string | null> {
  const response = await apiFetch("/api/chatgpt/accounts");
  if (!response.ok) throw new Error();
  return accountSchema.parse(await response.json()).find((account) => account.active)?.id ?? null;
}
async function refreshAccount() {
  const checked = loadedAccountId;
  if (checked === null) return;
  try {
    const active = await activeAccountId();
    if (loadedAccountId === checked && active !== checked) clearModels();
  } catch {
    if (loadedAccountId === checked) clearModels();
  }
}
onMounted(() => window.addEventListener("focus", refreshAccount));
onUnmounted(() => {
  window.removeEventListener("focus", refreshAccount);
  generation++;
});

async function loadModels() {
  const current = ++generation;
  busy.value = true;
  error.value = "";
  selectedModel.value = "";
  models.value = [];
  loaded.value = false;
  try {
    const accountId = await activeAccountId();
    if (!accountId) throw new Error("Connect a ChatGPT account first.");
    const response = await apiFetch("/api/chatgpt/models", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Spoiless-Action": "1" },
      body: JSON.stringify({ confirm: true }),
    });
    if (!response.ok) {
      const detail = z
        .object({ detail: z.string() })
        .safeParse(await response.json().catch(() => null));
      throw new Error(
        detail.success ? detail.data.detail : "Could not load ChatGPT models. Please retry.",
      );
    }
    const result = z
      .array(z.object({ slug: z.string(), display_name: z.string() }))
      .safeParse(await response.json().catch(() => null));
    if (!result.success) throw new Error("Could not load ChatGPT models. Please retry.");
    const active = await activeAccountId();
    if (generation === current) {
      if (active !== accountId) throw new Error("The active account changed. Please retry.");
      loadedAccountId = accountId;
      models.value = result.data;
      loaded.value = true;
    }
  } catch (err) {
    if (generation === current)
      error.value =
        err instanceof Error &&
        !(err instanceof TypeError) &&
        !(err instanceof z.ZodError) &&
        err.message
          ? err.message
          : "Could not load ChatGPT models. Check your connection and try again.";
  } finally {
    if (generation === current) busy.value = false;
  }
}
</script>

<template>
  <section class="models" aria-labelledby="models-title">
    <h2 id="models-title">ChatGPT model</h2>
    <p>Load models available to the selected ChatGPT account.</p>
    <button type="button" :disabled="busy" @click="loadModels">Load available models</button>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="loaded && !models.length" role="status">No models are available for this account.</p>
    <label v-if="models.length" for="chatgpt-model">ChatGPT model</label>
    <select v-if="models.length" id="chatgpt-model" v-model="selectedModel">
      <option value="">Choose a model</option>
      <option v-for="model in models" :key="model.slug" :value="model.slug">
        {{ model.display_name }}
      </option>
    </select>
  </section>
</template>

<style scoped>
.models {
  margin-top: 12px;
  padding: 16px;
  background: #fff;
  border: 1px solid #e2e2e2;
  border-radius: 8px;
}
h2 {
  margin: 0;
  font-size: 17px;
}
p {
  margin: 8px 0;
  color: #555;
  font-size: 14px;
}
label {
  display: block;
  font-size: 14px;
  margin-top: 12px;
}
select {
  font: inherit;
  width: 100%;
  min-height: 44px;
  padding: 8px;
}
button {
  width: 100%;
  font: inherit;
  min-height: 44px;
  padding: 8px 16px;
  border: 1px solid #aaa;
  border-radius: 6px;
  background: #fff;
}
</style>
