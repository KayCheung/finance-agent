<script setup lang="ts">
import { ref, computed, watch } from 'vue'

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
  total_amount?: string
  approval_status?: string
}

const props = defineProps<{ voucher: VoucherData | null }>()
const emit = defineEmits<{ confirm: [data: VoucherData] }>()

const entries = ref<VoucherEntry[]>([])
const summary = ref('')
const department = ref('')
const submitter = ref('')
const usage = ref('')

watch(() => props.voucher, (v) => {
  if (!v) return
  summary.value = v.summary || ''
  department.value = v.department || ''
  submitter.value = v.submitter || ''
  usage.value = v.usage || ''
  entries.value = (v.entries || []).map(e => ({
    account_code: e.account_code || '',
    account_name: e.account_name || '',
    debit: Number(e.debit) || 0,
    credit: Number(e.credit) || 0,
  }))
}, { immediate: true })

const totalDebit = computed(() => entries.value.reduce((sum, e) => sum + (Number(e.debit) || 0), 0))
const totalCredit = computed(() => entries.value.reduce((sum, e) => sum + (Number(e.credit) || 0), 0))
const balanced = computed(() => Math.abs(totalDebit.value - totalCredit.value) < 0.005)

function addEntry() {
  entries.value.push({ account_code: '', account_name: '', debit: 0, credit: 0 })
}

function removeEntry(index: number) {
  if (entries.value.length > 1) entries.value.splice(index, 1)
}

function confirmVoucher() {
  emit('confirm', {
    voucher_id: props.voucher?.voucher_id,
    summary: summary.value,
    department: department.value,
    submitter: submitter.value,
    usage: usage.value,
    entries: entries.value,
    total_debit: totalDebit.value,
    total_credit: totalCredit.value,
    balanced: balanced.value,
  })
}

function formatAmount(n: number): string { return n.toFixed(2) }
</script>

<template>
  <div class="voucher-editor" v-if="voucher">
    <h3>凭证编辑</h3>
    <div class="fields">
      <div class="field">
        <label>摘要</label>
        <input v-model="summary" />
      </div>
      <div class="field-row">
        <div class="field">
          <label>部门</label>
          <input v-model="department" />
        </div>
        <div class="field">
          <label>报销人</label>
          <input v-model="submitter" />
        </div>
      </div>
      <div class="field">
        <label>用途</label>
        <input v-model="usage" />
      </div>
    </div>

    <div class="entries-header">
      <span>分录明细</span>
      <button class="btn-add" @click="addEntry">+ 添加科目</button>
    </div>

    <table class="entries">
      <thead>
        <tr><th>科目代码</th><th>科目名称</th><th>借方</th><th>贷方</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="(entry, i) in entries" :key="i">
          <td><input v-model="entry.account_code" class="code-input" placeholder="如 6602.02" /></td>
          <td><input v-model="entry.account_name" placeholder="如 差旅费" /></td>
          <td><input v-model.number="entry.debit" type="number" step="0.01" min="0" class="amount-input" /></td>
          <td><input v-model.number="entry.credit" type="number" step="0.01" min="0" class="amount-input" /></td>
          <td><button class="btn-remove" @click="removeEntry(i)" :disabled="entries.length <= 1" title="删除">×</button></td>
        </tr>
      </tbody>
      <tfoot>
        <tr class="totals" :class="{ unbalanced: !balanced }">
          <td colspan="2" style="text-align:right;font-weight:600;">合计</td>
          <td>{{ formatAmount(totalDebit) }}</td>
          <td>{{ formatAmount(totalCredit) }}</td>
          <td></td>
        </tr>
      </tfoot>
    </table>

    <div class="balance-status" :class="{ ok: balanced, error: !balanced }">
      {{ balanced ? '✓ 借贷平衡' : '✗ 借贷不平衡，差额 ' + formatAmount(Math.abs(totalDebit - totalCredit)) }}
    </div>

    <button class="btn-confirm" @click="confirmVoucher" :disabled="!balanced">确认提交</button>
  </div>
  <div class="voucher-editor empty" v-else>
    <p>上传发票后，凭证将在此处显示</p>
  </div>
</template>

<style scoped>
.voucher-editor { padding: 16px; }
.voucher-editor.empty { text-align: center; color: #999; padding-top: 40px; }
h3 { margin: 0 0 12px; font-size: 16px; color: #333; }
.fields { margin-bottom: 16px; }
.field { margin-bottom: 8px; }
.field label { display: block; font-size: 12px; color: #666; margin-bottom: 2px; }
.field input { width: 100%; padding: 6px 8px; border: 1px solid #ddd; border-radius: 4px; font-size: 13px; box-sizing: border-box; }
.field input:focus { border-color: #409eff; outline: none; }
.field-row { display: flex; gap: 8px; }
.field-row .field { flex: 1; }
.entries-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 14px; font-weight: 600; }
.btn-add { padding: 4px 10px; font-size: 12px; background: #409eff; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
.btn-add:hover { background: #337ecc; }
.entries { width: 100%; border-collapse: collapse; font-size: 12px; }
.entries th, .entries td { border: 1px solid #eee; padding: 4px; }
.entries th { background: #f5f5f5; font-weight: 600; text-align: center; }
.entries td input { width: 100%; padding: 4px; border: 1px solid transparent; font-size: 12px; box-sizing: border-box; }
.entries td input:focus { border-color: #409eff; outline: none; }
.code-input { width: 80px !important; }
.amount-input { width: 80px !important; text-align: right; }
.totals td { font-weight: 600; background: #fafafa; }
.totals.unbalanced td { background: #fff1f0; color: #cf1322; }
.btn-remove { background: none; border: none; color: #999; font-size: 16px; cursor: pointer; padding: 0 4px; }
.btn-remove:hover:not(:disabled) { color: #cf1322; }
.btn-remove:disabled { opacity: 0.3; cursor: not-allowed; }
.balance-status { margin: 10px 0; padding: 6px 10px; border-radius: 4px; font-size: 13px; text-align: center; }
.balance-status.ok { background: #f6ffed; color: #389e0d; }
.balance-status.error { background: #fff1f0; color: #cf1322; }
.btn-confirm { width: 100%; padding: 10px; background: #409eff; color: #fff; border: none; border-radius: 6px; font-size: 14px; cursor: pointer; }
.btn-confirm:hover:not(:disabled) { background: #337ecc; }
.btn-confirm:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
