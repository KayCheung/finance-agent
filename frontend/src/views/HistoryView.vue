<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useSessionStore, type SessionSummary } from '../stores/session'
import { useRouter } from 'vue-router'

const sessionStore = useSessionStore()
const router = useRouter()
const selectedSession = ref<string | null>(null)

onMounted(() => {
  sessionStore.fetchSessions()
})

async function onSelectSession(session: SessionSummary) {
  selectedSession.value = session.session_id
  await sessionStore.loadSession(session.session_id)
  router.push({ name: 'reimbursement' })
}

async function onDeleteSession(sessionId: string) {
  await sessionStore.deleteSession(sessionId)
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN')
}
</script>

<template>
  <div class="history-view">
    <h2>历史会话</h2>
    <div v-if="sessionStore.sessions.length === 0" class="empty">暂无历史会话</div>
    <ul class="session-list" v-else>
      <li v-for="s in sessionStore.sessions" :key="s.session_id" class="session-item" :class="{ selected: selectedSession === s.session_id }">
        <div class="session-info" @click="onSelectSession(s)">
          <div class="session-id">{{ s.session_id.slice(0, 8) }}...</div>
          <div class="session-id" v-if="s.title">{{ s.title }}</div>
          <div class="session-meta">
            <span>创建: {{ formatDate(s.created_at) }}</span>
            <span>活跃: {{ formatDate(s.last_active) }}</span>
            <span>消息数: {{ s.message_count ?? s.voucher_count ?? 0 }}</span>
          </div>
        </div>
        <button class="delete-btn" @click.stop="onDeleteSession(s.session_id)">删除</button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.history-view { padding: 24px; max-width: 800px; }
h2 { margin-bottom: 16px; font-size: 20px; color: #333; }
.empty { color: #999; text-align: center; margin-top: 40px; }
.session-list { list-style: none; padding: 0; }
.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border: 1px solid #eee;
  border-radius: 8px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: background 0.15s;
}
.session-item:hover { background: #f5f7fa; }
.session-item.selected { border-color: #409eff; background: #ecf5ff; }
.session-info { flex: 1; }
.session-id { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
.session-meta { font-size: 12px; color: #999; display: flex; gap: 12px; }
.delete-btn {
  padding: 4px 12px;
  background: none;
  border: 1px solid #f56c6c;
  color: #f56c6c;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}
.delete-btn:hover { background: #fef0f0; }
</style>
