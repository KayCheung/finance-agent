<script setup lang="ts">
import { useUserStore } from '../stores/user'

const userStore = useUserStore()
</script>

<template>
  <div class="settings-view">
    <h2>系统设置</h2>
    <section class="settings-section">
      <h3>用户信息</h3>
      <div class="form-field">
        <label>用户 ID</label>
        <input v-model="userStore.user.user_id" type="text" />
      </div>
      <div class="form-field">
        <label>部门</label>
        <input v-model="userStore.user.department" type="text" />
      </div>
      <div class="form-field">
        <label>角色</label>
        <input v-model="userStore.user.role" type="text" />
      </div>
    </section>
    <section class="settings-section">
      <h3>系统信息</h3>
      <p class="info-text">后端地址: http://localhost:8001</p>
      <p class="info-text">版本: 2.0.0</p>
    </section>
  </div>
</template>

<style scoped>
.settings-view { padding: 24px; max-width: 600px; }
h2 { margin-bottom: 20px; font-size: 20px; color: #333; }
.settings-section {
  margin-bottom: 24px;
  padding: 16px;
  background: #fafafa;
  border-radius: 8px;
  border: 1px solid #eee;
}
h3 { margin-bottom: 12px; font-size: 16px; color: #333; }
.form-field { margin-bottom: 12px; }
.form-field label { display: block; font-size: 13px; color: #666; margin-bottom: 4px; }
.form-field input {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 14px;
  outline: none;
  box-sizing: border-box;
}
.form-field input:focus { border-color: #409eff; }
.info-text { font-size: 13px; color: #999; margin-bottom: 4px; }
</style>
