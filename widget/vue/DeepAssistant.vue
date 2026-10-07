<!--
  <DeepAssistant /> — Vue 3 wrapper around the <deep-assistant> web component.

  Drop this file into your app (ChampOracle: frontend/src/components/DeepAssistant.vue) and render it once in
  App.vue:   <DeepAssistant :api="assistantUrl" mode="launcher" @booking="onBooking" />

  Vite must treat the tag as a custom element. In vite.config.js:
    vue({ template: { compilerOptions: { isCustomElement: (tag) => tag === 'deep-assistant' } } })

  Identity: pass `token` (an HMAC token minted by your backend with the assistant's WIDGET_SIGNING_SECRET) or
  `userName` / `userEmail` as unverified prefill hints. See docs/WIDGET.md in the assistant repo.
-->
<template>
  <deep-assistant
    ref="el"
    :api="api"
    :mode="mode"
    :theme="theme"
    :title="title"
    :subtitle="subtitle"
    :suggestions="suggestions ? suggestions.join('|') : undefined"
    :user-name="userName"
    :user-email="userEmail"
    @deep-assistant:answer="(e) => emit('answer', e.detail)"
    @deep-assistant:booking="(e) => emit('booking', e.detail)"
    @deep-assistant:handover="(e) => emit('handover', e.detail)"
    @deep-assistant:feedback="(e) => emit('feedback', e.detail)"
    @deep-assistant:open="emit('open')"
    @deep-assistant:close="emit('close')"
  />
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'

const props = defineProps({
  api: { type: String, required: true },
  mode: { type: String, default: 'launcher' },      // 'panel' | 'launcher'
  theme: { type: String, default: 'auto' },         // 'auto' | 'dark' | 'light'
  title: String,
  subtitle: String,
  suggestions: Array,
  token: String,
  userName: String,
  userEmail: String,
  open: { type: Boolean, default: undefined },
})
const emit = defineEmits(['answer', 'booking', 'handover', 'feedback', 'open', 'close'])
const el = ref(null)

onMounted(() => {
  if (!customElements.get('deep-assistant')) {
    const s = document.createElement('script')
    s.type = 'module'
    s.src = `${props.api.replace(/\/+$/, '')}/static/deep-assistant.js`
    document.head.appendChild(s)
  }
  applyToken(props.token)
  applyOpen(props.open)
})
function applyToken(t) { if (!el.value) return; if (t) el.value.setAttribute('token', t); else el.value.removeAttribute('token') }
function applyOpen(o) { if (!el.value || o === undefined) return; if (o) el.value.setAttribute('open', ''); else el.value.removeAttribute('open') }
watch(() => props.token, applyToken)
watch(() => props.open, applyOpen)

defineExpose({
  ask: (text) => el.value && el.value.ask(text),
  open: () => el.value && el.value.open(),
  close: () => el.value && el.value.close(),
  reset: () => el.value && el.value.reset(),
})
</script>
