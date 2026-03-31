<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits<{
  select: [files: File[]]
}>()

const selectedFiles = ref<File[]>([])
const dragOver = ref(false)

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files && input.files.length > 0) {
    selectedFiles.value = Array.from(input.files)
    emit('select', selectedFiles.value)
  }
}

function onDrop(e: DragEvent) {
  dragOver.value = false
  if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
    selectedFiles.value = Array.from(e.dataTransfer.files)
    emit('select', selectedFiles.value)
  }
}

const fileInput = ref<HTMLInputElement | null>(null)

function clear() {
  selectedFiles.value = []
  if (fileInput.value) fileInput.value.value = ''
}

defineExpose({ clear })
</script>

<template>
  <div
    class="file-upload"
    :class="{ 'drag-over': dragOver }"
    @dragover.prevent="dragOver = true"
    @dragleave="dragOver = false"
    @drop.prevent="onDrop"
  >
    <label class="upload-label">
      <input type="file" accept="image/*" multiple @change="onFileChange" ref="fileInput" hidden />
      <span v-if="selectedFiles.length === 0">📎 点击或拖拽上传发票图片（可多选）</span>
      <span v-else-if="selectedFiles.length === 1">📄 {{ selectedFiles[0].name }}</span>
      <span v-else>📄 已选择 {{ selectedFiles.length }} 张图片</span>
    </label>
  </div>
</template>

<style scoped>
.file-upload {
  border: 2px dashed #ccc;
  border-radius: 8px;
  padding: 12px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s;
}
.file-upload:hover,
.file-upload.drag-over {
  border-color: #409eff;
}
.upload-label {
  cursor: pointer;
  color: #666;
  font-size: 14px;
}
</style>
