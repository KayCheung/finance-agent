import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface UserInfo {
  user_id: string
  department: string
  role: string
}

export const useUserStore = defineStore('user', () => {
  const user = ref<UserInfo>({
    user_id: 'default',
    department: '',
    role: 'user',
  })

  function setUser(info: Partial<UserInfo>) {
    user.value = { ...user.value, ...info }
  }

  return { user, setUser }
})
