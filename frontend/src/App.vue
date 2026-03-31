<script setup lang="ts">
import { onMounted } from 'vue'
import Sidebar from './components/Sidebar.vue'
import { useSessionStore } from './stores/session'

const sessionStore = useSessionStore()

onMounted(async () => {
  await sessionStore.restoreLatest()
})
</script>

<template>
  <div class="app-layout">
    <Sidebar />
    <main class="main-content">
      <router-view />
    </main>
  </div>
</template>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}
html, body, #app {
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}
.app-layout {
  display: flex;
  height: 100%;
}
.main-content {
  flex: 1;
  overflow: hidden;
  min-width: 0;
  min-height: 0;
  display: flex;
}
.main-content > * {
  flex: 1;
  min-width: 0;
  min-height: 0;
}
</style>
