<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Download, Eye, FileText, RefreshCw, Search, ShieldCheck, SlidersHorizontal, UserRound, Wrench } from '@lucide/vue'
import { api, downloadExport } from '../api'

const route = useRoute(); const router = useRouter()
const mode = computed(() => String(route.meta.module || 'minutes'))
const titleMap: Record<string, string> = { minutes: 'AI会议纪要', materials: '会议资料', transcription: '转写任务', review: '纪要自检', observability: '运行观测', models: 'AI模型配置', prompts: 'Prompt模板', departments: '部门管理', employees: '员工账号管理' }
const title = computed(() => titleMap[mode.value] || '会议中心')
const query = ref(''); const status = ref(''); const items = ref<any[]>([]); const loading = ref(false); const error = ref('')
const modelItems = ref<any[]>([]); const promptItems = ref<any[]>([]); const orgItems = ref<any[]>([])
const purposeLabel = (v: string) => ({ transcription: '音频转写', minutes_generation: '纪要生成', minutes_review: '纪要自检', speaker_matching: '说话人匹配' } as any)[v] || v
const variablesLabel = (vars: string[]) => (vars || []).map(v => `{{${v}}}`).join(' · ') || '无变量'
const statusLabel = (v: string) => ({ approved: '已确认', waiting_human: '待人工确认', draft: '待生成', ended: '已结束', running: '运行中', queued: '排队中', failed: '失败', succeeded: '已完成' } as any)[v] || v || '—'
const modeEndpoint: Record<string, string> = { minutes: '/meeting-center/minutes', materials: '/meeting-center/materials', transcription: '/meeting-center/transcription', review: '/assistant/runs', observability: '/assistant/observability' }

async function load() {
  loading.value = true; error.value = ''
  try {
    if (modeEndpoint[mode.value]) {
      const result: any = await api(modeEndpoint[mode.value] + (mode.value === 'minutes' ? `?query=${encodeURIComponent(query.value)}&status=${encodeURIComponent(status.value)}` : ''))
      items.value = result.items || result.jobs || []
      if (mode.value === 'observability') items.value = (result.jobs || []).map((x: any) => ({ ...x, row_type: 'job' })).concat((result.ai_calls || []).map((x: any) => ({ ...x, row_type: 'ai' })))
    } else if (mode.value === 'models') {
      modelItems.value = (await api('/admin/models')).items || []
    } else if (mode.value === 'prompts') {
      promptItems.value = (await api('/admin/prompts')).items || []
    } else if (mode.value === 'departments') {
      orgItems.value = (await api('/admin/departments')).items || []
    } else if (mode.value === 'employees') {
      orgItems.value = (await api('/admin/employees')).items || []
    }
  } catch (e: any) { error.value = e.message || '加载失败' } finally { loading.value = false }
}
async function selfCheck(row: any) { await api(`/meetings/${row.meeting_id}/review-runs`, { method: 'POST' }); await load() }
async function archive(row: any) { await api(`/meetings/${row.meeting_id}`, { method: 'PATCH', body: JSON.stringify({ status: 'archived' }) }); await load() }
async function saveModel(row: any) { await api(`/admin/models/${row.purpose}`, { method: 'PUT', body: JSON.stringify({ model: row.model, base_url: row.base_url, provider: row.provider, enabled: row.enabled }) }); await load() }
async function exportFile(row: any, format: 'docx'|'pdf') { await downloadExport(row.meeting_id, format) }
function refresh() { load() }
watch([mode, query, status], () => { if (mode.value === 'minutes') load() })
onMounted(load)
</script>

<template>
  <section class="module-page">
    <header class="module-heading"><div><div class="eyebrow">{{ mode === 'observability' ? 'OPERATIONS / OBSERVABILITY' : 'MEETING CENTER / CONTROL' }}</div><h1>{{ title }}</h1><p>按课程参考的模块化工作台组织数据、任务与人工确认动作。</p></div><button class="button" @click="refresh"><RefreshCw :size="16"/>刷新</button></header>
    <div v-if="error" class="notice error">{{ error }}</div>

    <section v-if="['minutes','materials','transcription','review','observability'].includes(mode)" class="module-card">
      <div class="module-toolbar" v-if="mode !== 'observability'"><label class="module-search"><Search :size="16"/><input v-model="query" placeholder="请输入会议主题或关键字"/></label><select v-if="mode === 'minutes'" v-model="status"><option value="">全部状态</option><option value="draft">待生成</option><option value="waiting_human">待人工确认</option><option value="approved">已确认</option></select><button class="button compact" @click="query='';status=''"><SlidersHorizontal :size="15"/>重置</button></div>
      <div v-if="loading" class="module-empty">正在加载模块数据…</div>
      <div v-else-if="mode === 'minutes'" class="table-scroll"><table class="module-table"><thead><tr><th>会议主题</th><th>音视频资料</th><th>状态</th><th>生成进度</th><th>生成模型</th><th>创建人</th><th>操作</th></tr></thead><tbody><tr v-for="row in items" :key="row.meeting_id"><td><strong>{{ row.title }}</strong><small>#{{ row.meeting_id }} · {{ row.meeting_status }}</small></td><td>{{ row.audio_file }}<small>{{ row.asset_count }} 个资料</small></td><td><span class="module-status" :class="row.status">{{ statusLabel(row.status) }}</span></td><td><div class="progress-cell"><i :style="{ width: `${row.progress || 0}%` }"></i><span>{{ row.progress || 0 }}%</span></div></td><td>{{ row.model }}</td><td>{{ row.creator }}<small>{{ row.created_at?.slice(0,16).replace('T',' ') }}</small></td><td class="module-actions"><button @click="router.push(`/meetings/${row.meeting_id}`)"><Eye :size="14"/>详情</button><button @click="router.push(`/meetings/${row.meeting_id}/minutes`)">修订</button><button @click="selfCheck(row)"><ShieldCheck :size="14"/>Agent自检</button><button @click="exportFile(row,'docx')"><Download :size="14"/>Word</button><button @click="exportFile(row,'pdf')">PDF</button><button class="danger" @click="archive(row)">归档</button></td></tr></tbody></table></div>
      <div v-else-if="mode === 'materials'" class="table-scroll"><table class="module-table"><thead><tr><th>资料名称</th><th>所属会议</th><th>类型</th><th>大小</th><th>上传时间</th><th>操作</th></tr></thead><tbody><tr v-for="row in items" :key="row.id"><td><FileText :size="16"/> {{ row.file_name }}</td><td>{{ row.meeting_title }}</td><td>{{ row.kind }}</td><td>{{ Math.ceil((row.size_bytes || 0) / 1024) }} KB</td><td>{{ row.created_at?.slice(0,16).replace('T',' ') }}</td><td><button class="text-link" @click="router.push(`/meetings/${row.meeting_id}`)">查看会议</button></td></tr></tbody></table></div>
      <div v-else-if="mode === 'transcription'" class="table-scroll"><table class="module-table"><thead><tr><th>任务</th><th>会议</th><th>状态</th><th>进度</th><th>尝试</th><th>更新时间</th></tr></thead><tbody><tr v-for="row in items" :key="row.id"><td><strong>转写任务 #{{ row.id }}</strong><small>{{ row.kind }}</small></td><td>{{ row.meeting_title }}</td><td><span class="module-status" :class="row.status">{{ statusLabel(row.status) }}</span></td><td><div class="progress-cell"><i :style="{ width: `${row.progress || 0}%` }"></i><span>{{ row.progress || 0 }}%</span></div></td><td>{{ row.attempt }}/{{ row.max_attempts }}</td><td>{{ row.updated_at?.slice(0,16).replace('T',' ') }}</td></tr></tbody></table></div>
      <div v-else-if="mode === 'review'" class="table-scroll"><table class="module-table"><thead><tr><th>会议</th><th>状态</th><th>轮次</th><th>评分</th><th>问题数</th><th>操作</th></tr></thead><tbody><tr v-for="row in items" :key="row.id"><td><strong>{{ row.meeting_title }}</strong><small>运行 #{{ row.id }}</small></td><td><span class="module-status" :class="row.status">{{ statusLabel(row.status) }}</span></td><td>{{ row.current_round }}/{{ row.max_rounds }}</td><td>{{ row.score || 0 }}</td><td>{{ row.issues?.length || 0 }}</td><td class="module-actions"><button @click="router.push(`/reviews/${row.id}`)">打开运行台</button></td></tr></tbody></table></div>
      <div v-else class="table-scroll"><table class="module-table"><thead><tr><th>类型</th><th>模型/任务</th><th>状态</th><th>耗时</th><th>Token</th><th>时间</th></tr></thead><tbody><tr v-for="row in items" :key="`${row.row_type}-${row.id}`"><td>{{ row.row_type === 'ai' ? 'AI调用' : '后台任务' }}</td><td>{{ row.row_type === 'ai' ? purposeLabel(row.purpose) + ' · ' + row.model : row.kind }}</td><td><span class="module-status" :class="row.success === false || row.status === 'failed' ? 'failed' : 'succeeded'">{{ row.success === false || row.status === 'failed' ? '失败' : '正常' }}</span></td><td>{{ row.duration_ms || 0 }} ms</td><td>{{ (row.prompt_tokens || 0) + (row.completion_tokens || 0) }}</td><td>{{ (row.created_at || row.updated_at || '').slice(0,16).replace('T',' ') }}</td></tr></tbody></table></div>
      <div v-if="!loading && !items.length" class="module-empty">暂无数据</div>
    </section>

    <section v-else-if="mode === 'models'" class="module-grid"> <article v-for="row in modelItems" :key="row.purpose" class="module-card config-card"><header><div><div class="eyebrow">{{ purposeLabel(row.purpose) }}</div><h2>{{ row.model }}</h2></div><span class="module-status" :class="row.enabled ? 'approved' : 'failed'">{{ row.enabled ? '启用' : '停用' }}</span></header><label>服务商<input v-model="row.provider"/></label><label>接口地址<input v-model="row.base_url"/></label><footer><button class="button primary compact" @click="saveModel(row)">保存配置</button><span class="mono">更新于 {{ row.updated_at?.slice(0,16).replace('T',' ') }}</span></footer></article></section>
    <section v-else-if="mode === 'prompts'" class="module-grid"> <article v-for="row in promptItems" :key="row.id" class="module-card prompt-card"><header><div><div class="eyebrow">{{ purposeLabel(row.purpose) }} · V{{ row.version }}</div><h2>{{ row.name }}</h2></div><span class="module-status approved">{{ row.enabled ? '当前版本' : '历史版本' }}</span></header><textarea v-model="row.template" rows="8"></textarea><footer><span>{{ variablesLabel(row.variables) }}</span><button class="button compact" @click="router.push('/admin')">进入版本管理</button></footer></article></section>
    <section v-else class="module-card"><div class="module-toolbar"><span class="eyebrow">{{ mode === 'departments' ? 'ORGANIZATION / DEPARTMENTS' : 'ORGANIZATION / EMPLOYEES' }}</span><span>{{ orgItems.length }} 条记录</span></div><div class="table-scroll"><table class="module-table"><thead><tr><th>名称</th><th>编码/账号</th><th>角色/职位</th><th>部门</th><th>状态</th></tr></thead><tbody><tr v-for="row in orgItems" :key="row.id"><td><UserRound :size="15"/> {{ row.name || row.display_name }}</td><td>{{ row.code || row.username }}</td><td>{{ row.title || row.role || '—' }}</td><td>{{ row.department_name || '—' }}</td><td><span class="module-status" :class="row.enabled ? 'approved' : 'failed'">{{ row.enabled ? '启用' : '停用' }}</span></td></tr></tbody></table></div></section>
  </section>
</template>
