<!--
  Comma-separated text field bound to a string[].

  Replaces <o-taginput>: in Oruga 0.13 its internal input ref never picks up
  what you type unless the parent drives it, so Enter adds nothing and the tag
  list stays empty. (<o-inputitems>, what this codebase used before, doesn't
  exist in 0.13 at all — it rendered as an unknown element with no input.)
  A plain text field does the job with no version coupling.
-->
<template>
  <o-input
    :model-value="text"
    :placeholder="placeholder"
    @update:model-value="onInput"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{ modelValue?: string[] | null; placeholder?: string }>(),
  { modelValue: () => [], placeholder: 'comma, separated, values' },
)
const emit = defineEmits<{ 'update:modelValue': [string[]] }>()

const text = computed(() => (props.modelValue ?? []).join(', '))

function onInput(v: string | undefined) {
  emit(
    'update:modelValue',
    String(v ?? '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean),
  )
}
</script>
