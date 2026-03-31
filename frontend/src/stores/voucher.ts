import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface VoucherEntry {
  account_code: string
  account_name: string
  debit: string
  credit: string
}

export interface VoucherRecord {
  voucher_id: string
  created_at: string
  department: string
  submitter: string
  summary: string
  usage: string
  entries: VoucherEntry[]
  total_amount: string
  approval_status: string
  approval_id: string | null
  expense_type: string
}

export const useVoucherStore = defineStore('voucher', () => {
  const vouchers = ref<VoucherRecord[]>([])
  const currentVoucher = ref<VoucherRecord | null>(null)
  const loading = ref(false)

  async function queryVouchers(params: Record<string, string> = {}) {
    loading.value = true
    try {
      const query = new URLSearchParams(params).toString()
      const url = query ? `/vouchers?${query}` : '/vouchers'
      const res = await fetch(url)
      if (res.ok) {
        vouchers.value = await res.json()
      }
    } finally {
      loading.value = false
    }
  }

  async function getVoucher(voucherId: string) {
    loading.value = true
    try {
      const res = await fetch(`/vouchers/${voucherId}`)
      if (res.ok) {
        currentVoucher.value = await res.json()
      }
    } finally {
      loading.value = false
    }
  }

  return { vouchers, currentVoucher, loading, queryVouchers, getVoucher }
})
