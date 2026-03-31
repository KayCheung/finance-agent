<script setup lang="ts">
import { useRouter, useRoute } from 'vue-router'
import SessionManager from './SessionManager.vue'

const router = useRouter()
const route = useRoute()

function navigate(name: string) {
  router.push({ name })
}
</script>

<template>
  <aside class="sidebar">
    <div class="logo">财务报销 Agent</div>
    <nav class="nav">
      <button class="nav-item" :class="{ active: route.name === 'reimbursement' }" @click="navigate('reimbursement')">
        报销对话
      </button>
      <button class="nav-item" :class="{ active: route.name === 'settings' }" @click="navigate('settings')">
        系统设置
      </button>
    </nav>

    <SessionManager />
  </aside>
</template>

<style scoped>
.sidebar {
  width: 240px;
  background: #1a1a2e;
  color: #eee;
  display: flex;
  flex-direction: column;
  padding: 16px 0;
  flex-shrink: 0;
}
.logo {
  padding: 0 16px 16px;
  font-size: 16px;
  font-weight: 700;
  border-bottom: 1px solid #333;
}
.nav {
  padding: 12px 0;
}
.nav-item {
  display: block;
  width: 100%;
  padding: 10px 16px;
  background: none;
  border: none;
  color: #ccc;
  font-size: 14px;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s;
}
.nav-item:hover {
  background: rgba(255, 255, 255, 0.08);
}
.nav-item.active {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
}
</style>
