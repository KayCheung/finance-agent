<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import ChatView from '../components/ChatView.vue'
import { useSessionStore } from '../stores/session'

interface ConfirmedVoucher {
  voucher_id?: string
  summary?: string
  department?: string
  submitter?: string
  entries: { account_code: string; account_name: string; debit: number; credit: number }[]
  total_debit?: number
  total_credit?: number
  confirmed_at: string
}

const confirmedVouchers = ref<ConfirmedVoucher[]>([])
const sessionStore = useSessionStore()
const voucherPanelWidth = ref(320)
const isResizing = ref(false)
const minVoucherWidth = 260
const maxVoucherWidthRatio = 0.6
const storageKey = 'finance-agent:voucher-panel-width'

function extractConfirmedVouchers(): ConfirmedVoucher[] {
  return sessionStore.messages
    .filter((m) => m.role === 'assistant' && m.voucher && m.confirmed)
    .map((m) => {
      const voucher = m.voucher as any
      const entries = Array.isArray(voucher.entries) ? voucher.entries : []
      return {
        voucher_id: voucher.voucher_id,
        summary: voucher.summary,
        department: voucher.department,
        submitter: voucher.submitter,
        entries,
        total_debit: voucher.total_debit,
        total_credit: voucher.total_credit,
        confirmed_at: m.time || '',
      }
    })
}

function onVoucherConfirmed(data: any) {
  const voucherId = data?.voucher_id
  if (voucherId && confirmedVouchers.value.some((v) => v.voucher_id === voucherId)) return
  confirmedVouchers.value.unshift({
    ...data,
    confirmed_at: new Date().toLocaleString('zh-CN'),
  })
}

function fmt(n: number): string { return (n || 0).toFixed(2) }
function formatDateTime(value: string): string {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value || ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function getMaxVoucherWidth(): number {
  return Math.max(minVoucherWidth, Math.floor(window.innerWidth * maxVoucherWidthRatio))
}

function clampVoucherWidth(nextWidth: number): number {
  return Math.min(Math.max(nextWidth, minVoucherWidth), getMaxVoucherWidth())
}

function onResizeStart() {
  if (window.innerWidth <= 960) return
  isResizing.value = true
  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'col-resize'
}

function onResizeMove(event: MouseEvent) {
  if (!isResizing.value) return
  const next = window.innerWidth - event.clientX
  voucherPanelWidth.value = clampVoucherWidth(next)
}

function onResizeEnd() {
  if (!isResizing.value) return
  isResizing.value = false
  document.body.style.userSelect = ''
  document.body.style.cursor = ''
  localStorage.setItem(storageKey, String(voucherPanelWidth.value))
}

function onWindowResize() {
  voucherPanelWidth.value = clampVoucherWidth(voucherPanelWidth.value)
}

watch(
  () => [sessionStore.currentSessionId, sessionStore.messages],
  () => {
    confirmedVouchers.value = extractConfirmedVouchers()
  },
  { immediate: true, deep: true },
)

onMounted(() => {
  const saved = Number(localStorage.getItem(storageKey) || 0)
  if (saved > 0) voucherPanelWidth.value = clampVoucherWidth(saved)
  window.addEventListener('mousemove', onResizeMove)
  window.addEventListener('mouseup', onResizeEnd)
  window.addEventListener('resize', onWindowResize)
})

onUnmounted(() => {
  window.removeEventListener('mousemove', onResizeMove)
  window.removeEventListener('mouseup', onResizeEnd)
  window.removeEventListener('resize', onWindowResize)
})
</script>

<template>
  <div class="reimbursement-view">
    <div class="chat-panel">
      <ChatView @voucher-confirmed="onVoucherConfirmed" />
    </div>
    <div
      class="panel-splitter"
      :class="{ dragging: isResizing }"
      @mousedown="onResizeStart"
    />
    <div
      class="voucher-panel"
      :style="{ width: `${voucherPanelWidth}px` }"
    >
      <h3>已确认凭证</h3>
      <div v-if="confirmedVouchers.length === 0" class="empty">暂无已确认凭证</div>
      <div v-for="(v, i) in confirmedVouchers" :key="i" class="confirmed-card">
        <div class="card-header">
          <span class="vid">{{ v.voucher_id || `凭证 ${i + 1}` }}</span>
          <span class="badge">✓ 已确认</span>
        </div>
        <div class="card-time">{{ formatDateTime(v.confirmed_at) }}</div>
        <div class="card-meta" v-if="v.department || v.submitter">
          {{ v.department }} / {{ v.submitter }}
        </div>
        <table class="card-table">
          <thead><tr><th>科目</th><th>借方</th><th>贷方</th></tr></thead>
          <tbody>
            <tr v-for="(e, j) in v.entries" :key="j">
              <td>{{ e.account_name }}</td>
              <td class="amt">{{ fmt(Number(e.debit)) }}</td>
              <td class="amt">{{ fmt(Number(e.credit)) }}</td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <td style="font-weight:600">合计</td>
              <td class="amt">{{ fmt(Number(v.total_debit)) }}</td>
              <td class="amt">{{ fmt(Number(v.total_credit)) }}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.reimbursement-view { display: flex; height: 100%; gap: 1px; background: #eee; min-width: 0; min-height: 0; }
.chat-panel { flex: 1; background: #fff; display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.panel-splitter { width: 8px; background: #f3f3f3; cursor: col-resize; flex-shrink: 0; position: relative; }
.panel-splitter::after { content: ''; position: absolute; left: 3px; top: 0; width: 2px; height: 100%; background: #d9d9d9; }
.panel-splitter:hover::after, .panel-splitter.dragging::after { background: #1677ff; }
.voucher-panel { width: 300px; background: #fff; overflow-y: auto; flex-shrink: 0; padding: 16px; }
.voucher-panel h3 { margin: 0 0 12px; font-size: 15px; color: #333; }
.empty { color: #999; font-size: 13px; text-align: center; margin-top: 30px; }
.confirmed-card { border: 1px solid #e0e0e0; border-radius: 8px; padding: 10px; margin-bottom: 12px; }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.vid { font-weight: 600; font-size: 13px; }
.badge { font-size: 11px; color: #389e0d; background: #f6ffed; padding: 2px 6px; border-radius: 4px; }
.card-meta { font-size: 12px; color: #666; margin-bottom: 6px; }
.card-time { font-size: 11px; color: #999; margin-bottom: 6px; }
.card-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.card-table th, .card-table td { border: 1px solid #eee; padding: 3px 6px; }
.card-table th { background: #f5f5f5; text-align: left; }
.amt { text-align: right; font-family: monospace; }

@media (max-width: 960px) {
  .reimbursement-view { flex-direction: column; gap: 0; }
  .chat-panel { min-height: 0; }
  .panel-splitter { display: none; }
  .voucher-panel { width: 100%; max-height: 42%; border-top: 1px solid #eee; }
}
</style>
