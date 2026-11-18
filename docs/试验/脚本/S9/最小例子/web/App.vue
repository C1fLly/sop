<script setup>
import { ref, computed } from 'vue'
const items = ref([{ note: '午饭', fen: 1250 }])
const note = ref(''); const yuan = ref('')
const total = computed(() => (items.value.reduce((s, i) => s + i.fen, 0) / 100).toFixed(2))
function add() { items.value.push({ note: note.value, fen: Math.round(Number(yuan.value) * 100) }); note.value = ''; yuan.value = '' }
</script>
<template>
  <main style="font-family: sans-serif; width: 320px; padding: 16px">
    <h1>记账</h1>
    <input aria-label="说明" v-model="note" /> <input aria-label="金额" v-model="yuan" /> <button @click="add">记一笔</button>
    <ul><li v-for="(i, k) in items" :key="k">{{ i.note }} {{ (i.fen / 100).toFixed(2) }} 元</li></ul>
    <p data-testid="total">一共 {{ total }} 元，共 {{ items.length }} 笔</p>
  </main>
</template>
