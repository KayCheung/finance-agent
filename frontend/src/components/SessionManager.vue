<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useSessionStore, type SessionSummary } from '../stores/session'

const router = useRouter()
const sessionStore = useSessionStore()
const searchText = ref('')
const showArchived = ref(false)

const visibleSessions = computed(() => sessionStore.sessions.slice(0, 40))
const pinnedSessions = computed(() => visibleSessions.value.filter((s) => !!s.pinned && !s.archived))
const recentSessions = computed(() => visibleSessions.value.filter((s) => !s.pinned && !s.archived))
const archivedSessions = computed(() => visibleSessions.value.filter((s) => !!s.archived))

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function highlight(text: string): string {
  const raw = String(text || '')
  const kw = searchText.value.trim()
  if (!kw) return escapeHtml(raw)
  const parts = raw.split(new RegExp(`(${escapeRegExp(kw)})`, 'ig'))
  return parts
    .map((part) => (part.toLowerCase() === kw.toLowerCase() ? `<mark>${escapeHtml(part)}</mark>` : escapeHtml(part)))
    .join('')
}

async function onNewSession() {
  await sessionStore.newSession()
  router.push({ name: 'reimbursement' })
}

async function onSelectSession(sessionId: string) {
  await sessionStore.loadSession(sessionId)
  router.push({ name: 'reimbursement' })
}

async function onTogglePin(sessionId: string, pinned: boolean) {
  await sessionStore.updateSession(sessionId, { pinned: !pinned })
}

async function onToggleArchive(session: SessionSummary) {
  await sessionStore.updateSession(session.session_id, { archived: !session.archived })
}

async function onDeleteSession(sessionId: string) {
  await sessionStore.deleteSession(sessionId)
}

async function onRenameSession(sessionId: string, currentTitle: string) {
  const title = window.prompt('请输入会话标题', currentTitle || '')
  if (title === null) return
  await sessionStore.updateSession(sessionId, { title: title.trim() })
}

async function onSearch() {
  await sessionStore.fetchSessions(searchText.value, showArchived.value)
}

async function onToggleShowArchived() {
  await sessionStore.fetchSessions(searchText.value, showArchived.value)
}

onMounted(async () => {
  searchText.value = sessionStore.sessionSearchKeyword
  showArchived.value = sessionStore.includeArchived
  if (sessionStore.sessions.length === 0) {
    await sessionStore.fetchSessions(searchText.value, showArchived.value)
  }
})
</script>

<template>
  <div class="session-panel">
    <div class="session-head">
      <span>会话</span>
      <button class="new-session-btn mini" @click="onNewSession">+ 新建</button>
    </div>
    <input
      v-model="searchText"
      class="session-search"
      type="text"
      placeholder="搜索会话"
      @keyup.enter="onSearch"
    />
    <label class="archive-switch">
      <input v-model="showArchived" type="checkbox" @change="onToggleShowArchived" />
      显示归档
    </label>

    <div class="session-list">
      <template v-if="pinnedSessions.length > 0">
        <div class="group-title">置顶</div>
        <div v-for="s in pinnedSessions" :key="s.session_id" class="session-item" :class="{ active: sessionStore.currentSessionId === s.session_id }">
          <div class="session-main" @click="onSelectSession(s.session_id)">
            <div class="session-title" v-html="highlight(s.title || `${s.session_id.slice(0, 8)}...`)" />
            <div class="session-preview" v-html="highlight(s.preview || '暂无内容')" />
          </div>
          <div class="session-actions">
            <button class="icon-btn" title="取消置顶" @click.stop="onTogglePin(s.session_id, true)">取消置顶</button>
            <button class="icon-btn" title="重命名" @click.stop="onRenameSession(s.session_id, s.title || '')">改名</button>
            <button class="icon-btn" title="归档" @click.stop="onToggleArchive(s)">归档</button>
            <button class="icon-btn danger" title="删除" @click.stop="onDeleteSession(s.session_id)">删除</button>
          </div>
        </div>
      </template>

      <template v-if="recentSessions.length > 0">
        <div class="group-title">最近</div>
        <div v-for="s in recentSessions" :key="s.session_id" class="session-item" :class="{ active: sessionStore.currentSessionId === s.session_id }">
          <div class="session-main" @click="onSelectSession(s.session_id)">
            <div class="session-title" v-html="highlight(s.title || `${s.session_id.slice(0, 8)}...`)" />
            <div class="session-preview" v-html="highlight(s.preview || '暂无内容')" />
          </div>
          <div class="session-actions">
            <button class="icon-btn" title="置顶" @click.stop="onTogglePin(s.session_id, false)">置顶</button>
            <button class="icon-btn" title="重命名" @click.stop="onRenameSession(s.session_id, s.title || '')">改名</button>
            <button class="icon-btn" title="归档" @click.stop="onToggleArchive(s)">归档</button>
            <button class="icon-btn danger" title="删除" @click.stop="onDeleteSession(s.session_id)">删除</button>
          </div>
        </div>
      </template>

      <template v-if="showArchived && archivedSessions.length > 0">
        <div class="group-title">归档</div>
        <div v-for="s in archivedSessions" :key="s.session_id" class="session-item" :class="{ active: sessionStore.currentSessionId === s.session_id }">
          <div class="session-main" @click="onSelectSession(s.session_id)">
            <div class="session-title" v-html="highlight(s.title || `${s.session_id.slice(0, 8)}...`)" />
            <div class="session-preview" v-html="highlight(s.preview || '暂无内容')" />
          </div>
          <div class="session-actions">
            <button class="icon-btn" title="取消归档" @click.stop="onToggleArchive(s)">取消归档</button>
            <button class="icon-btn danger" title="删除" @click.stop="onDeleteSession(s.session_id)">删除</button>
          </div>
        </div>
      </template>

      <div v-if="visibleSessions.length === 0" class="session-empty">暂无会话</div>
    </div>
  </div>
</template>

<style scoped>
.session-panel {
  padding: 8px 12px 12px;
  border-top: 1px solid #333;
  border-bottom: 1px solid #333;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.session-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: #bbb;
  margin-bottom: 8px;
}
.session-search {
  width: 100%;
  border: 1px solid #444;
  background: #121224;
  color: #ddd;
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 12px;
  margin-bottom: 8px;
}
.archive-switch {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #b8b8c8;
  margin-bottom: 8px;
}
.session-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.group-title {
  font-size: 11px;
  color: #8d8da0;
  margin: 8px 2px 6px;
}
.session-empty {
  color: #888;
  font-size: 12px;
  text-align: center;
  padding: 14px 0;
}
.session-item {
  border: 1px solid #2f2f45;
  border-radius: 6px;
  margin-bottom: 6px;
  background: #121224;
  padding: 6px;
}
.session-item.active {
  border-color: #409eff;
}
.session-main {
  cursor: pointer;
}
.session-title {
  font-size: 12px;
  color: #eee;
  white-space: nowrap;
  text-overflow: ellipsis;
  overflow: hidden;
}
.session-preview {
  margin-top: 3px;
  font-size: 11px;
  color: #8f8f9f;
  white-space: nowrap;
  text-overflow: ellipsis;
  overflow: hidden;
}
.session-actions {
  margin-top: 6px;
  display: flex;
  justify-content: flex-end;
  gap: 4px;
  flex-wrap: wrap;
}
.icon-btn {
  border: 1px solid #3b3b52;
  background: #1c1c33;
  color: #ddd;
  border-radius: 4px;
  font-size: 11px;
  padding: 2px 6px;
  cursor: pointer;
}
.icon-btn.danger {
  color: #ff9b9b;
}
.new-session-btn {
  width: 100%;
  padding: 8px;
  background: #409eff;
  color: #fff;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.new-session-btn.mini {
  width: auto;
  padding: 4px 8px;
  font-size: 11px;
}
.new-session-btn:hover {
  background: #337ecc;
}
:deep(mark) {
  background: #ffec99;
  color: #1f1f1f;
  border-radius: 2px;
  padding: 0 1px;
}
</style>
