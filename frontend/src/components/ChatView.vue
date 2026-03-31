<script setup lang="ts">
import { ref, nextTick, watch, computed, onMounted, onUnmounted } from 'vue'
import { useSessionStore } from '../stores/session'
import { marked } from 'marked'
import FileUpload from './FileUpload.vue'

interface VoucherEntry {
  account_code: string
  account_name: string
  debit: number
  credit: number
}

interface VoucherData {
  voucher_id?: string
  summary?: string
  department?: string
  submitter?: string
  usage?: string
  entries: VoucherEntry[]
  total_debit?: number
  total_credit?: number
  balanced?: boolean
}

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  imageUrls?: string[]
  voucher?: VoucherData | null
  confirmed?: boolean
  time: string
}

interface ProfileState {
  department: string
  usage: string
  submitter: string
}

const sessionStore = useSessionStore()
const inputText = ref('')
const sending = ref(false)
const chatContainer = ref<HTMLElement | null>(null)
const fileUploadRef = ref<InstanceType<typeof FileUpload> | null>(null)
const selectedFiles = ref<File[]>([])

const messages = ref<ChatMessage[]>([])
const previewVisible = ref(false)
const previewIndex = ref(0)
const collaborationMode = ref<'quick' | 'careful'>('careful')

const missingInfoVisible = ref(false)
const missingInfoNeed = ref({ department: false, usage: false, submitter: false })
const missingInfoForm = ref({ department: '', usage: '', submitter: '' })
const missingInfoSessionId = ref('')

const confirmModalVisible = ref(false)
const confirmModalChecked = ref(false)
const confirmModalVoucher = ref<VoucherData | null>(null)

function mapStoreMessage(m: any): ChatMessage {
  let imageUrls: string[] = []
  if (Array.isArray(m?.image_list)) {
    imageUrls = m.image_list
      .filter((x: any) => x && x.image_base64)
      .map((x: any) => `data:${String(x.image_mime || 'image/png')};base64,${String(x.image_base64)}`)
  } else if (m?.image_base64) {
    imageUrls = [`data:${String(m.image_mime || 'image/png')};base64,${String(m.image_base64)}`]
  }
  const content = m.role === 'assistant'
    ? cleanReply(String(m.content || ''))
    : String(m.content || (m.image_filename ? `上传文件: ${m.image_filename}` : ''))
  return {
    role: m.role,
    content,
    imageUrls,
    voucher: m.voucher || null,
    confirmed: !!m.confirmed,
    time: m.time || '',
  }
}

const emit = defineEmits<{
  voucherConfirmed: [data: VoucherData]
}>()

const imageItems = computed(() =>
  messages.value
    .flatMap((m) => (m.imageUrls || []).map((url) => ({ url })))
)

const currentPreviewImage = computed(() => imageItems.value[previewIndex.value]?.url || '')

function onFileSelect(files: File[]) {
  selectedFiles.value = files
}

function openImagePreview(url: string) {
  const idx = imageItems.value.findIndex((item) => item.url === url)
  if (idx < 0) return
  previewIndex.value = idx
  previewVisible.value = true
}

function closeImagePreview() {
  previewVisible.value = false
}

function prevImage() {
  if (imageItems.value.length === 0) return
  previewIndex.value = (previewIndex.value - 1 + imageItems.value.length) % imageItems.value.length
}

function nextImage() {
  if (imageItems.value.length === 0) return
  previewIndex.value = (previewIndex.value + 1) % imageItems.value.length
}

function onPreviewKeydown(e: KeyboardEvent) {
  if (!previewVisible.value) return
  if (e.key === 'Escape') closeImagePreview()
  if (e.key === 'ArrowLeft') prevImage()
  if (e.key === 'ArrowRight') nextImage()
}

function cleanReply(text: string): string {
  return text.replace(/%%VOUCHER_JSON_START%%[\s\S]*?%%VOUCHER_JSON_END%%/g, '').trim()
}

function renderMarkdown(text: string): string {
  return marked.parse(text, { async: false }) as string
}

function nowTime(): string {
  return formatDateTime(new Date())
}

function formatDateTime(value: string | Date): string {
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return String(value || '')
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

const editingVoucher = ref<VoucherData | null>(null)
const editEntries = ref<VoucherEntry[]>([])
const originalEditEntries = ref<VoucherEntry[]>([])
const editChecked = ref(false)

watch(
  () => [sessionStore.currentSessionId, sessionStore.messages],
  () => {
    messages.value = sessionStore.messages.map(mapStoreMessage)
    editingVoucher.value = null
    if (missingInfoVisible.value && missingInfoSessionId.value && missingInfoSessionId.value !== sessionStore.currentSessionId) {
      missingInfoVisible.value = false
    }
  },
  { immediate: true, deep: true },
)

const editTotalDebit = computed(() =>
  editEntries.value.reduce((s, e) => s + (Number(e.debit) || 0), 0)
)
const editTotalCredit = computed(() =>
  editEntries.value.reduce((s, e) => s + (Number(e.credit) || 0), 0)
)
const editBalanced = computed(() =>
  Math.abs(editTotalDebit.value - editTotalCredit.value) < 0.005
)

const editDiffLines = computed(() => {
  const lines: string[] = []
  const maxLen = Math.max(originalEditEntries.value.length, editEntries.value.length)
  for (let i = 0; i < maxLen; i += 1) {
    const oldE = originalEditEntries.value[i]
    const newE = editEntries.value[i]
    if (!oldE && newE) {
      lines.push(`新增第${i + 1}行：${newE.account_name || '-'} 借${fmt(newE.debit || 0)} 贷${fmt(newE.credit || 0)}`)
      continue
    }
    if (oldE && !newE) {
      lines.push(`删除第${i + 1}行：${oldE.account_name || '-'} 借${fmt(oldE.debit || 0)} 贷${fmt(oldE.credit || 0)}`)
      continue
    }
    if (!oldE || !newE) continue
    if (
      oldE.account_code !== newE.account_code ||
      oldE.account_name !== newE.account_name ||
      Number(oldE.debit) !== Number(newE.debit) ||
      Number(oldE.credit) !== Number(newE.credit)
    ) {
      lines.push(`修改第${i + 1}行：${oldE.account_name || '-'} -> ${newE.account_name || '-'}；借${fmt(Number(oldE.debit) || 0)} -> ${fmt(Number(newE.debit) || 0)}；贷${fmt(Number(oldE.credit) || 0)} -> ${fmt(Number(newE.credit) || 0)}`)
    }
  }
  return lines
})

function cloneEntries(entries: VoucherEntry[] = []): VoucherEntry[] {
  return entries.map((e) => ({
    account_code: e.account_code || '',
    account_name: e.account_name || '',
    debit: Number(e.debit) || 0,
    credit: Number(e.credit) || 0,
  }))
}

function startEditVoucher(v: VoucherData) {
  editingVoucher.value = v
  editEntries.value = cloneEntries(v.entries || [])
  originalEditEntries.value = cloneEntries(v.entries || [])
  editChecked.value = false
}

function addEditEntry() {
  editEntries.value.push({ account_code: '', account_name: '', debit: 0, credit: 0 })
}

function removeEditEntry(i: number) {
  if (editEntries.value.length > 1) editEntries.value.splice(i, 1)
}

let pendingConfirmVoucher: VoucherData | null = null

function buildVoucherForConfirm(v: VoucherData): VoucherData {
  return {
    ...v,
    entries: cloneEntries(v.entries || []),
    total_debit: Number(v.total_debit) || (v.entries || []).reduce((s, e) => s + (Number(e.debit) || 0), 0),
    total_credit: Number(v.total_credit) || (v.entries || []).reduce((s, e) => s + (Number(e.credit) || 0), 0),
    balanced: v.balanced ?? true,
  }
}

function openConfirmModal(voucher: VoucherData) {
  confirmModalVoucher.value = buildVoucherForConfirm(voucher)
  confirmModalChecked.value = false
  confirmModalVisible.value = true
}

function closeConfirmModal() {
  confirmModalVisible.value = false
  confirmModalVoucher.value = null
  confirmModalChecked.value = false
}

function executeConfirm(voucher: VoucherData) {
  pendingConfirmVoucher = buildVoucherForConfirm(voucher)
  closeConfirmModal()
  sendMessage('确认凭证')
}

function confirmVoucher() {
  if (!editingVoucher.value) return
  const drafted: VoucherData = {
    ...editingVoucher.value,
    entries: cloneEntries(editEntries.value),
    total_debit: editTotalDebit.value,
    total_credit: editTotalCredit.value,
    balanced: editBalanced.value,
  }
  editingVoucher.value = null

  if (collaborationMode.value === 'careful') {
    openConfirmModal(drafted)
    return
  }
  executeConfirm(drafted)
}

function fmt(n: number): string { return (n || 0).toFixed(2) }

function directConfirm(v: VoucherData) {
  if (collaborationMode.value === 'careful') {
    openConfirmModal(v)
    return
  }
  executeConfirm(v)
}

function detectMissingInfo(text: string): { department: boolean; usage: boolean; submitter: boolean } {
  const t = String(text || '').replace(/\s+/g, '')
  const askLike = /(请提供|请补充|还需要|还需|需要以下信息|需要更多信息|缺失的信息|为了完成报销凭证|请您确认|请确认|请输入|请填写|是否为|一旦您提供)/.test(t)
  if (!askLike) return { department: false, usage: false, submitter: false }
  if (/(凭证预览|凭证已确认|已加入已确认凭证列表)/.test(t)) {
    return { department: false, usage: false, submitter: false }
  }
  return {
    department: /(部门|归属部门|所属部门)/.test(t),
    usage: /(用途|费用类型|费用用途|报销项目)/.test(t),
    submitter: /(报销人|提交人|申请人|经办人|报销人姓名|提交人姓名|申请人姓名|经办人姓名)/.test(t),
  }
}

function inferKnownProfileFromMessages(list: ChatMessage[]): ProfileState {
  const profile: ProfileState = { department: '', usage: '', submitter: '' }
  const patterns = {
    department: /(?:部门|所属部门|归属部门)\s*[:：]?\s*([^\s，。,；;]+)/,
    usage: /(?:用途|费用用途|报销用途|费用类型)\s*[:：]?\s*([^\s，。,；;]+)/,
    submitter: /(?:报销人|提交人|申请人|经办人)(?:姓名)?\s*[:：]?\s*([^\s，。,；;]+)/,
  }

  for (let i = list.length - 1; i >= 0; i -= 1) {
    const msg = list[i]
    if (!msg) continue
    if (msg.voucher) {
      if (!profile.department && msg.voucher.department) profile.department = String(msg.voucher.department)
      if (!profile.usage && msg.voucher.usage) profile.usage = String(msg.voucher.usage)
      if (!profile.submitter && msg.voucher.submitter) profile.submitter = String(msg.voucher.submitter)
    }
    if (msg.role !== 'user') continue
    const content = String(msg.content || '')
    if (!profile.department) {
      const m = content.match(patterns.department)
      if (m) profile.department = m[1]
    }
    if (!profile.usage) {
      const m = content.match(patterns.usage)
      if (m) profile.usage = m[1]
    }
    if (!profile.submitter) {
      const m = content.match(patterns.submitter)
      if (m) profile.submitter = m[1]
    }
    if (profile.department && profile.usage && profile.submitter) break
  }
  return profile
}

const missingInfoReady = computed(() => {
  if (missingInfoNeed.value.department && !missingInfoForm.value.department.trim()) return false
  if (missingInfoNeed.value.usage && !missingInfoForm.value.usage.trim()) return false
  if (missingInfoNeed.value.submitter && !missingInfoForm.value.submitter.trim()) return false
  return true
})

async function submitMissingInfo() {
  if (!missingInfoReady.value) return
  const chunks: string[] = []
  if (missingInfoNeed.value.department) chunks.push(`部门:${missingInfoForm.value.department.trim()}`)
  if (missingInfoNeed.value.usage) chunks.push(`用途:${missingInfoForm.value.usage.trim()}`)
  if (missingInfoNeed.value.submitter) chunks.push(`报销人:${missingInfoForm.value.submitter.trim()}`)
  missingInfoVisible.value = false
  await sendMessage(chunks.join(' '))
}

async function sendMessage(overrideText?: string) {
  const text = (overrideText ?? inputText.value).trim()
  if (!text && selectedFiles.value.length === 0) return
  if (sending.value) return

  sending.value = true

  const imageUrls = selectedFiles.value.map((f) => URL.createObjectURL(f))
  const uploadLabel = selectedFiles.value.length === 1
    ? `上传文件: ${selectedFiles.value[0].name}`
    : selectedFiles.value.length > 1
      ? `上传文件(${selectedFiles.value.length}): ${selectedFiles.value.map((f) => f.name).join(', ')}`
      : ''
  const userMsg: ChatMessage = {
    role: 'user',
    content: text || uploadLabel,
    imageUrls,
    time: nowTime(),
  }
  messages.value.push(userMsg)
  if (overrideText === undefined) {
    inputText.value = ''
  }
  await scrollToBottom()

  try {
    const formData = new FormData()
    formData.append('session_id', sessionStore.currentSessionId)
    formData.append('message', text)
    for (const file of selectedFiles.value) {
      formData.append('files', file)
    }

    const res = await fetch('/agent/chat', { method: 'POST', body: formData })
    const data = await res.json()

    const reply = cleanReply(data.reply || '处理完成')
    const assistantMsg: ChatMessage = {
      role: 'assistant',
      content: reply,
      voucher: data.voucher_data || null,
      time: nowTime(),
    }
    messages.value.push(assistantMsg)

    const need = detectMissingInfo(reply)
    const askedMissing = need.department || need.usage || need.submitter
    const known = inferKnownProfileFromMessages(messages.value)
    if (!missingInfoForm.value.department && known.department) missingInfoForm.value.department = known.department
    if (!missingInfoForm.value.usage && known.usage) missingInfoForm.value.usage = known.usage
    if (!missingInfoForm.value.submitter && known.submitter) missingInfoForm.value.submitter = known.submitter

    const normalizedNeed = {
      department: askedMissing && !missingInfoForm.value.department.trim(),
      usage: askedMissing && !missingInfoForm.value.usage.trim(),
      submitter: askedMissing && !missingInfoForm.value.submitter.trim(),
    }
    const hasNeed = askedMissing && (normalizedNeed.department || normalizedNeed.usage || normalizedNeed.submitter)
    if (hasNeed) {
      missingInfoNeed.value = normalizedNeed
      missingInfoSessionId.value = sessionStore.currentSessionId
      missingInfoVisible.value = true
    } else if (data.voucher_data) {
      missingInfoVisible.value = false
    }

    if (pendingConfirmVoucher) {
      if (data.success !== false) {
        messages.value.forEach(m => { if (m.voucher) m.confirmed = true })
        emit('voucherConfirmed', pendingConfirmVoucher)
      }
      pendingConfirmVoucher = null
    } else if (data.action === 'posted' && data.success !== false) {
      const latestVoucherMsg = [...messages.value]
        .reverse()
        .find(m => m.role === 'assistant' && m.voucher && !m.confirmed)
      if (latestVoucherMsg?.voucher) {
        latestVoucherMsg.confirmed = true
        emit('voucherConfirmed', latestVoucherMsg.voucher)
      }
    }
  } catch {
    messages.value.push({ role: 'assistant', content: '请求失败，请重试。', time: nowTime() })
  } finally {
    sending.value = false
    selectedFiles.value = []
    fileUploadRef.value?.clear()
    await scrollToBottom()
  }
}

async function scrollToBottom() {
  await nextTick()
  if (chatContainer.value) {
    chatContainer.value.scrollTop = chatContainer.value.scrollHeight
  }
}

watch(() => messages.value.length, scrollToBottom)
watch(
  () => messages.value[messages.value.length - 1],
  (lastMsg) => {
    if (!lastMsg || lastMsg.role !== 'assistant') return
    const need = detectMissingInfo(lastMsg.content || '')
    const askedMissing = need.department || need.usage || need.submitter
    const known = inferKnownProfileFromMessages(messages.value)
    if (!missingInfoForm.value.department && known.department) missingInfoForm.value.department = known.department
    if (!missingInfoForm.value.usage && known.usage) missingInfoForm.value.usage = known.usage
    if (!missingInfoForm.value.submitter && known.submitter) missingInfoForm.value.submitter = known.submitter
    const normalizedNeed = {
      department: askedMissing && !missingInfoForm.value.department.trim(),
      usage: askedMissing && !missingInfoForm.value.usage.trim(),
      submitter: askedMissing && !missingInfoForm.value.submitter.trim(),
    }
    if (askedMissing && (normalizedNeed.department || normalizedNeed.usage || normalizedNeed.submitter)) {
      missingInfoNeed.value = normalizedNeed
      missingInfoSessionId.value = sessionStore.currentSessionId
      missingInfoVisible.value = true
    }
  },
  { deep: true },
)
watch(collaborationMode, (v) => {
  localStorage.setItem('finance-agent:collab-mode', v)
})

onMounted(() => {
  const mode = localStorage.getItem('finance-agent:collab-mode')
  if (mode === 'quick' || mode === 'careful') collaborationMode.value = mode
  window.addEventListener('keydown', onPreviewKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onPreviewKeydown)
})
</script>

<template>
  <div class="chat-view">
    <div class="messages" ref="chatContainer">
      <div v-for="(msg, i) in messages" :key="i" class="message" :class="msg.role">
        <div class="bubble-wrap">
          <div class="bubble">
            <img
              v-for="(img, imgIdx) in (msg.imageUrls || [])"
              :key="`${i}-${imgIdx}`"
              :src="img"
              class="preview-img preview-clickable"
              @click="openImagePreview(img)"
            />
            <div v-if="msg.role === 'assistant'" class="md-content" v-html="renderMarkdown(msg.content)"></div>
            <template v-else>{{ msg.content }}</template>

            <div v-if="msg.voucher && msg.voucher.entries && msg.voucher.entries.length > 0" class="voucher-card" :class="{ 'vc-confirmed': msg.confirmed }">
              <div class="vc-title">{{ msg.confirmed ? '凭证已确认' : '凭证预览' }}</div>
              <table class="vc-table">
                <thead>
                  <tr><th>科目代码</th><th>科目名称</th><th>借方</th><th>贷方</th></tr>
                </thead>
                <tbody>
                  <tr v-for="(e, j) in msg.voucher.entries" :key="j">
                    <td>{{ e.account_code }}</td>
                    <td>{{ e.account_name }}</td>
                    <td class="amt">{{ fmt(Number(e.debit) || 0) }}</td>
                    <td class="amt">{{ fmt(Number(e.credit) || 0) }}</td>
                  </tr>
                </tbody>
              </table>
              <div v-if="!msg.confirmed" class="vc-btn-row">
                <button class="vc-edit-btn" @click="startEditVoucher(msg.voucher!)">编辑凭证</button>
                <button class="vc-confirm-btn" @click="directConfirm(msg.voucher!)">确认凭证</button>
              </div>
            </div>
          </div>
          <div v-if="msg.time" class="msg-time">{{ formatDateTime(msg.time) }}</div>
        </div>
      </div>

      <div v-if="editingVoucher" class="message assistant">
        <div class="bubble voucher-editor-inline">
          <div class="vc-title">编辑凭证</div>
          <table class="vc-table editable">
            <thead>
              <tr><th>科目代码</th><th>科目名称</th><th>借方</th><th>贷方</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="(e, j) in editEntries" :key="j">
                <td><input v-model="e.account_code" placeholder="6602.02" /></td>
                <td><input v-model="e.account_name" placeholder="差旅费" /></td>
                <td><input v-model.number="e.debit" type="number" step="0.01" min="0" /></td>
                <td><input v-model.number="e.credit" type="number" step="0.01" min="0" /></td>
                <td><button class="rm-btn" @click="removeEditEntry(j)" :disabled="editEntries.length<=1">×</button></td>
              </tr>
            </tbody>
            <tfoot>
              <tr :class="{ unbalanced: !editBalanced }">
                <td colspan="2" style="text-align:right;font-weight:600">合计</td>
                <td class="amt">{{ fmt(editTotalDebit) }}</td>
                <td class="amt">{{ fmt(editTotalCredit) }}</td>
                <td></td>
              </tr>
            </tfoot>
          </table>

          <div v-if="editDiffLines.length > 0" class="diff-box">
            <div class="diff-title">提交前差异（{{ editDiffLines.length }}项）</div>
            <ul>
              <li v-for="(line, idx) in editDiffLines" :key="idx">{{ line }}</li>
            </ul>
          </div>

          <div v-if="collaborationMode === 'careful'" class="check-row">
            <label>
              <input v-model="editChecked" type="checkbox" /> 已核对差异和借贷平衡
            </label>
          </div>

          <div class="vc-actions">
            <button class="add-btn" @click="addEditEntry">+ 添加科目</button>
            <span class="balance-tag" :class="{ ok: editBalanced, err: !editBalanced }">
              {{ editBalanced ? '借贷平衡' : '差额 ' + fmt(Math.abs(editTotalDebit - editTotalCredit)) }}
            </span>
            <button class="confirm-btn" @click="confirmVoucher" :disabled="!editBalanced || (collaborationMode === 'careful' && !editChecked)">确认提交</button>
          </div>
        </div>
      </div>

      <div v-if="missingInfoVisible" class="message assistant">
        <div class="bubble collab-card">
          <div class="vc-title">协作补充信息</div>
          <div class="collab-desc">为减少往返对话，请一次补全以下信息。</div>
          <div class="collab-form">
            <input v-if="missingInfoNeed.department" v-model="missingInfoForm.department" placeholder="报销部门" />
            <input v-if="missingInfoNeed.usage" v-model="missingInfoForm.usage" placeholder="费用用途（如差旅费）" />
            <input v-if="missingInfoNeed.submitter" v-model="missingInfoForm.submitter" placeholder="报销人姓名" />
          </div>
          <div class="collab-actions">
            <button class="vc-confirm-btn" :disabled="!missingInfoReady || sending" @click="submitMissingInfo">一键提交信息</button>
          </div>
        </div>
      </div>

      <div v-if="messages.length === 0" class="empty-hint">上传发票图片开始报销对话</div>
    </div>

    <div v-if="confirmModalVisible && confirmModalVoucher" class="confirm-mask" @click.self="closeConfirmModal">
      <div class="confirm-dialog">
        <h3>确认提交凭证</h3>
        <p>摘要：{{ confirmModalVoucher.summary || '-' }}</p>
        <p>部门：{{ confirmModalVoucher.department || '-' }}；报销人：{{ confirmModalVoucher.submitter || '-' }}</p>
        <p>借方合计：{{ fmt(Number(confirmModalVoucher.total_debit) || 0) }}；贷方合计：{{ fmt(Number(confirmModalVoucher.total_credit) || 0) }}</p>
        <label v-if="collaborationMode === 'careful'" class="check-row">
          <input v-model="confirmModalChecked" type="checkbox" /> 我已完成人工复核
        </label>
        <div class="dialog-actions">
          <button class="add-btn" @click="closeConfirmModal">取消</button>
          <button class="vc-confirm-btn" :disabled="collaborationMode === 'careful' && !confirmModalChecked" @click="executeConfirm(confirmModalVoucher)">确认提交</button>
        </div>
      </div>
    </div>

    <div v-if="previewVisible" class="image-lightbox" @click="closeImagePreview">
      <div class="lightbox-content" @click.stop>
        <button class="lightbox-btn close" @click="closeImagePreview" aria-label="关闭预览">×</button>
        <button class="lightbox-btn nav left" @click="prevImage" :disabled="imageItems.length <= 1" aria-label="上一张">‹</button>
        <img :src="currentPreviewImage" class="lightbox-image" />
        <button class="lightbox-btn nav right" @click="nextImage" :disabled="imageItems.length <= 1" aria-label="下一张">›</button>
        <div class="lightbox-index">{{ previewIndex + 1 }} / {{ imageItems.length }}</div>
      </div>
    </div>

    <div class="input-area">
      <div class="mode-row">
        <span>协作模式：</span>
        <button class="mode-btn" :class="{ active: collaborationMode === 'quick' }" @click="collaborationMode = 'quick'">快速</button>
        <button class="mode-btn" :class="{ active: collaborationMode === 'careful' }" @click="collaborationMode = 'careful'">审慎</button>
      </div>
      <FileUpload ref="fileUploadRef" @select="onFileSelect" />
      <div class="input-row">
        <input v-model="inputText" type="text" placeholder="输入消息..." @keyup.enter="sendMessage()" :disabled="sending" />
        <button @click="sendMessage()" :disabled="sending">{{ sending ? '发送中...' : '发送' }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-view { display: flex; flex-direction: column; height: 100%; min-width: 0; min-height: 0; }
.messages { flex: 1; overflow-y: auto; padding: 16px; min-height: 0; }
.message { margin-bottom: 12px; display: flex; width: 100%; }
.message.user { justify-content: flex-end; }
.message.assistant { justify-content: flex-start; }
.bubble-wrap { display: flex; flex-direction: column; max-width: min(85%, 900px); }
.message.user .bubble-wrap { margin-left: auto; align-items: flex-end; }
.message.assistant .bubble-wrap { align-items: flex-start; }
.bubble { max-width: 100%; width: fit-content; padding: 10px 14px; border-radius: 12px; font-size: 14px; line-height: 1.6; word-break: break-word; overflow-wrap: anywhere; }
.user .bubble { background: #409eff; color: #fff; }
.assistant .bubble { background: #f0f0f0; color: #333; }
.msg-time { font-size: 11px; color: #999; margin-top: 2px; }
.user .msg-time { text-align: right; }
.assistant .msg-time { text-align: left; }
.preview-img { max-width: 200px; max-height: 160px; border-radius: 8px; display: block; margin-bottom: 6px; }
.preview-clickable { cursor: zoom-in; }
.md-content { overflow-x: auto; max-width: 100%; }
.md-content :deep(p) { margin: 0.3em 0; }
.md-content :deep(ul), .md-content :deep(ol) { padding-left: 1.2em; margin: 0.3em 0; }
.md-content :deep(strong) { font-weight: 600; }
.md-content :deep(code) { background: #e8e8e8; padding: 1px 4px; border-radius: 3px; font-size: 13px; }
.md-content :deep(pre) { background: #2d2d2d; color: #f8f8f2; padding: 10px; border-radius: 6px; overflow-x: auto; font-size: 13px; }
.md-content :deep(table) { border-collapse: collapse; margin: 0.5em 0; font-size: 13px; }
.md-content :deep(th), .md-content :deep(td) { border: 1px solid #ccc; padding: 4px 8px; }
.voucher-card { margin-top: 10px; background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 10px; max-width: 100%; overflow-x: auto; }
.voucher-card.vc-confirmed { border-color: #52c41a; background: #f6ffed; }
.vc-title { font-weight: 600; font-size: 14px; margin-bottom: 8px; }
.vc-table { width: 100%; min-width: 460px; border-collapse: collapse; font-size: 12px; }
.vc-table th, .vc-table td { border: 1px solid #eee; padding: 4px 8px; text-align: left; }
.vc-table th { background: #f5f5f5; }
.amt { text-align: right; font-family: monospace; }
.vc-btn-row { display: flex; gap: 8px; margin-top: 8px; }
.vc-edit-btn { padding: 4px 12px; background: #409eff; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; }
.vc-edit-btn:hover { background: #337ecc; }
.vc-confirm-btn { padding: 4px 12px; background: #52c41a; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; }
.vc-confirm-btn:hover { background: #449d1a; }
.voucher-editor-inline { background: #fff; border: 2px solid #409eff; max-width: 95%; }
.editable input { width: 100%; padding: 3px 4px; border: 1px solid #ddd; border-radius: 3px; font-size: 12px; box-sizing: border-box; }
.editable input:focus { border-color: #409eff; outline: none; }
.editable input[type="number"] { width: 80px; text-align: right; }
.rm-btn { background: none; border: none; color: #999; font-size: 16px; cursor: pointer; }
.rm-btn:hover:not(:disabled) { color: #cf1322; }
.rm-btn:disabled { opacity: 0.3; }
.unbalanced td { background: #fff1f0; color: #cf1322; }
.vc-actions { display: flex; align-items: center; gap: 10px; margin-top: 8px; flex-wrap: wrap; }
.add-btn { padding: 4px 10px; font-size: 12px; background: #f0f0f0; border: 1px solid #ddd; border-radius: 4px; cursor: pointer; }
.add-btn:hover { background: #e0e0e0; }
.balance-tag { font-size: 12px; }
.balance-tag.ok { color: #389e0d; }
.balance-tag.err { color: #cf1322; }
.confirm-btn { margin-left: auto; padding: 6px 16px; background: #52c41a; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
.confirm-btn:hover:not(:disabled) { background: #449d1a; }
.confirm-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.diff-box { margin-top: 8px; padding: 8px; border: 1px solid #ffe58f; background: #fffbe6; border-radius: 6px; font-size: 12px; }
.diff-title { font-weight: 600; margin-bottom: 4px; }
.diff-box ul { margin: 0; padding-left: 16px; }
.check-row { font-size: 12px; color: #555; margin-top: 8px; }
.collab-card { background: #fff; border: 1px solid #91d5ff; }
.collab-desc { font-size: 12px; color: #666; margin-bottom: 8px; }
.collab-form { display: flex; flex-wrap: wrap; gap: 8px; }
.collab-form input { min-width: 180px; flex: 1; padding: 6px 8px; border: 1px solid #d9d9d9; border-radius: 6px; font-size: 12px; }
.collab-actions { margin-top: 8px; }
.empty-hint { text-align: center; color: #999; margin-top: 40px; font-size: 14px; }
.input-area { padding: 12px 16px; border-top: 1px solid #eee; }
.mode-row { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #666; margin-bottom: 8px; }
.mode-btn { padding: 3px 8px; border-radius: 999px; border: 1px solid #d9d9d9; background: #fff; cursor: pointer; font-size: 12px; }
.mode-btn.active { border-color: #409eff; color: #1677ff; background: #eaf3ff; }
.input-row { display: flex; gap: 8px; margin-top: 8px; }
.input-row input { flex: 1; padding: 10px 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; outline: none; }
.input-row input:focus { border-color: #409eff; }
.input-row button { flex-shrink: 0; padding: 10px 20px; background: #409eff; color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; }
.input-row button:disabled { opacity: 0.6; cursor: not-allowed; }
.confirm-mask { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.5); z-index: 1800; display: flex; align-items: center; justify-content: center; padding: 16px; }
.confirm-dialog { width: min(92vw, 520px); background: #fff; border-radius: 10px; padding: 14px; box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2); }
.confirm-dialog h3 { margin: 0 0 10px; font-size: 16px; }
.confirm-dialog p { margin: 6px 0; font-size: 13px; color: #333; }
.dialog-actions { margin-top: 12px; display: flex; justify-content: flex-end; gap: 8px; }
.image-lightbox { position: fixed; inset: 0; z-index: 2000; background: rgba(0, 0, 0, 0.72); display: flex; align-items: center; justify-content: center; padding: 16px; }
.lightbox-content { position: relative; width: min(96vw, 1200px); height: min(88vh, 860px); display: flex; align-items: center; justify-content: center; }
.lightbox-image { max-width: 100%; max-height: 100%; border-radius: 8px; object-fit: contain; background: #111; }
.lightbox-btn { position: absolute; width: 40px; height: 40px; border: none; border-radius: 999px; background: rgba(255, 255, 255, 0.2); color: #fff; cursor: pointer; font-size: 24px; line-height: 1; }
.lightbox-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.lightbox-btn.close { top: -6px; right: -6px; }
.lightbox-btn.nav.left { left: 8px; }
.lightbox-btn.nav.right { right: 8px; }
.lightbox-index { position: absolute; bottom: 8px; left: 50%; transform: translateX(-50%); color: #fff; font-size: 13px; background: rgba(0, 0, 0, 0.5); border-radius: 999px; padding: 4px 10px; }

@media (max-width: 768px) {
  .messages { padding: 12px; }
  .bubble-wrap { max-width: 94%; }
  .input-area { padding: 10px 12px; }
  .input-row { gap: 6px; }
  .input-row button { padding: 10px 14px; }
  .lightbox-btn { width: 36px; height: 36px; }
  .lightbox-btn.nav.left { left: 2px; }
  .lightbox-btn.nav.right { right: 2px; }
}
</style>
