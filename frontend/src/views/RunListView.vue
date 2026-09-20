<template>
  <div class="page">
    <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px">
      <div>
        <h1 style="margin-bottom: 4px">实验 Run 列表</h1>
        <p class="muted" style="margin-top: 0">按项目、状态与代码提交哈希筛选投影视图</p>
      </div>
      <n-button v-if="auth.role === 'researcher'" type="primary" @click="$router.push('/runs/new')">
        新建 Run
      </n-button>
    </div>

    <div class="card" style="margin-bottom: 16px">
      <div class="grid-2">
        <n-form-item label="项目" :show-feedback="false">
          <n-input v-model:value="project" clearable placeholder="例如 protein-folding" />
        </n-form-item>
        <n-form-item label="状态" :show-feedback="false">
          <n-select
            v-model:value="status"
            clearable
            :options="statusOptions"
            placeholder="全部"
          />
        </n-form-item>
        <n-form-item label="代码提交哈希" :show-feedback="false">
          <n-input
            v-model:value="commitSha"
            class="mono"
            clearable
            placeholder="完整哈希或开头片段，例如 a1b2c3d"
          />
        </n-form-item>
        <n-form-item label="哈希匹配模式" :show-feedback="false">
          <n-radio-group v-model:value="commitShaMode" size="small">
            <n-radio-button value="exact">精确匹配</n-radio-button>
            <n-radio-button value="prefix">前缀匹配</n-radio-button>
          </n-radio-group>
        </n-form-item>
      </div>
      <p class="muted" style="margin: 4px 0 0; font-size: 12px">
        哈希匹配不区分大小写（输入统一按小写比较）。精确匹配：需与完整提交哈希一致；前缀匹配：命中以输入片段开头的提交。筛选在服务端完成，可与项目、状态组合；无命中时列表为空，不会退回全量列表。
      </p>
      <n-button style="margin-top: 8px" @click="load">筛选</n-button>
    </div>

    <div class="card">
      <n-data-table :columns="columns" :data="rows" :loading="loading" :bordered="false">
        <template #empty>
          <n-empty description="没有匹配的 Run">
            <template #extra>
              <span class="muted" style="font-size: 12px">
                当前筛选条件无命中，请调整项目 / 状态 / 提交哈希后重试
              </span>
            </template>
          </n-empty>
        </template>
      </n-data-table>
    </div>
  </div>
</template>

<script setup>
import { h, onMounted, ref } from 'vue'
import { NButton, NTag, useMessage } from 'naive-ui'
import { useRouter } from 'vue-router'
import { listRuns } from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const message = useMessage()
const rows = ref([])
const loading = ref(false)
const project = ref('')
const status = ref(null)
const commitSha = ref('')
const commitShaMode = ref('exact')

const statusOptions = [
  { label: '进行中', value: 'running' },
  { label: '已完成', value: 'completed' },
  { label: '已中止', value: 'aborted' },
]

const statusMap = {
  running: { type: 'info', label: '进行中' },
  completed: { type: 'success', label: '已完成' },
  aborted: { type: 'warning', label: '已中止' },
}

const columns = [
  { title: '项目', key: 'project' },
  { title: '名称', key: 'name' },
  {
    title: '状态',
    key: 'status',
    render(row) {
      const m = statusMap[row.status] || { type: 'default', label: row.status }
      return h(NTag, { type: m.type, size: 'small' }, { default: () => m.label })
    },
  },
  { title: '版本', key: 'version', width: 70 },
  {
    title: '提交哈希',
    key: 'code_commit_sha',
    ellipsis: { tooltip: true },
    render(row) {
      return h('span', { class: 'mono' }, row.code_commit_sha)
    },
  },
  {
    title: '开始时间',
    key: 'started_at',
    render(row) {
      return new Date(row.started_at).toLocaleString()
    },
  },
  {
    title: '操作',
    key: 'actions',
    render(row) {
      return h(
        'div',
        { style: 'display:flex;gap:8px;flex-wrap:wrap' },
        [
          h(NButton, { size: 'tiny', onClick: () => router.push(`/runs/${row.id}`) }, { default: () => '详情' }),
          h(NButton, { size: 'tiny', quaternary: true, onClick: () => router.push(`/runs/${row.id}/events`) }, { default: () => '事件' }),
          h(NButton, { size: 'tiny', quaternary: true, onClick: () => router.push(`/runs/${row.id}/lineage`) }, { default: () => '血缘' }),
        ],
      )
    },
  },
]

async function load() {
  loading.value = true
  try {
    const params = {}
    if (project.value.trim()) params.project = project.value.trim()
    if (status.value) params.status = status.value
    const sha = commitSha.value.trim()
    if (sha) {
      params.commit_sha = sha
      params.commit_sha_mode = commitShaMode.value
    }
    // 服务端过滤：无命中时返回空数组，列表保持空态，不回退全表
    rows.value = await listRuns(params)
  } catch (e) {
    message.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
