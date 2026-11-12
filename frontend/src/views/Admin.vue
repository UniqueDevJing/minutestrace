<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Activity, Cpu, Database, RefreshCw, Save, Users, WandSparkles } from '@lucide/vue'
import { api } from '../api'

const section = ref<'observability' | 'models' | 'prompts' | 'organization'>('observability')
const data = ref<any>(null)
const models = ref<any[]>([])
const prompts = ref<any[]>([])
const departments = ref<any[]>([])
const employees = ref<any[]>([])
const error = ref('')
const saving = ref<number | string>('')
const newDepartment = reactive({ name: '', code: '' })
const newEmployee = reactive({ username: '', display_name: '', password: '', role: 'employee', department_id: '', title: '' })

async function load() {
  error.value = ''
  try {
    const [observability, modelData, promptData, departmentData, employeeData] = await Promise.all([
      api('/admin/observability'), api('/admin/models'), api('/admin/prompts'), api('/admin/departments'), api('/admin/employees'),
    ])
    data.value = observability; models.value = modelData.items; prompts.value = promptData.items
    departments.value = departmentData.items; employees.value = employeeData.items
  } catch (reason: any) { error.value = reason.message }
}

async function saveModel(item: any) {
  saving.value = `model-${item.purpose}`
  try { Object.assign(item, await api(`/admin/models/${item.purpose}`, { method: 'PUT', body: JSON.stringify({ model: item.model, base_url: item.base_url, provider: item.provider, enabled: item.enabled }) })) }
  catch (reason: any) { error.value = reason.message } finally { saving.value = '' }
}

async function savePrompt(item: any) {
  saving.value = `prompt-${item.id}`
  try { const created = await api('/admin/prompts', { method: 'POST', body: JSON.stringify({ purpose: item.purpose, name: item.name, template: item.template, variables: item.variables || [] }) }); prompts.value.unshift(created) }
  catch (reason: any) { error.value = reason.message } finally { saving.value = '' }
}

async function addDepartment() {
  if (!newDepartment.name || !newDepartment.code) return
  try { departments.value.push(await api('/admin/departments', { method: 'POST', body: JSON.stringify(newDepartment) })); newDepartment.name = ''; newDepartment.code = '' }
  catch (reason: any) { error.value = reason.message }
}

async function addEmployee() {
  try { await api('/admin/employees', { method: 'POST', body: JSON.stringify({ ...newEmployee, department_id: newEmployee.department_id ? Number(newEmployee.department_id) : null }) }); Object.assign(newEmployee, { username: '', display_name: '', password: '', role: 'employee', department_id: '', title: '' }); await load() }
  catch (reason: any) { error.value = reason.message }
}

const fmt = (value: string) => new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
const purposeLabel = (value: string) => ({ transcription: '音频转写', minutes_generation: '纪要生成', minutes_review: '纪要审查', speaker_matching: '说话人匹配' } as any)[value] || value
const purposeStats = computed(() => Object.entries(data.value?.summary?.by_purpose || {}).map(([purpose, value]: any) => ({ purpose, ...value })))
onMounted(load)
</script>

<template>
  <section class="page-heading admin-heading">
    <div><div class="eyebrow">Operations / Control room</div><h1>看见模型如何工作，<br>也能改它。</h1><p>任务、模型、Prompt 和组织权限统一在一个低噪声控制舱。</p></div>
    <button class="button" @click="load"><RefreshCw :size="17"/>刷新数据</button>
  </section>
  <div v-if="error" class="notice error" style="margin-bottom:16px">{{ error }}</div>
  <nav class="admin-tabs" aria-label="管理员模块">
    <button :class="{ active: section === 'observability' }" @click="section='observability'"><Activity :size="16"/>运行观测</button>
    <button :class="{ active: section === 'models' }" @click="section='models'"><Cpu :size="16"/>模型配置</button>
    <button :class="{ active: section === 'prompts' }" @click="section='prompts'"><WandSparkles :size="16"/>Prompt 版本</button>
    <button :class="{ active: section === 'organization' }" @click="section='organization'"><Users :size="16"/>组织管理</button>
  </nav>

  <div v-if="!data" class="loading">LOADING CONTROL ROOM…</div>
  <section v-else-if="section === 'observability'">
    <section class="grid four admin-stats">
      <article class="card stat-card"><Activity :size="20"/><div><span class="eyebrow">排队任务</span><strong>{{data.summary.jobs_queued}}</strong></div></article>
      <article class="card stat-card"><Database :size="20"/><div><span class="eyebrow">失败任务</span><strong>{{data.summary.jobs_failed}}</strong></div></article>
      <article class="card stat-card"><Cpu :size="20"/><div><span class="eyebrow">模型调用</span><strong>{{data.summary.ai_calls}}</strong></div></article>
      <article class="card stat-card dark"><Cpu :size="20"/><div><span class="eyebrow" style="color:var(--teal-bright)">模型失败</span><strong>{{data.summary.ai_failures}}</strong></div></article>
    </section>
    <section class="grid two admin-grid">
      <article class="card paper"><header class="card-header"><div><div class="kicker">Job queue</div><h2>任务队列</h2></div></header><div class="list-stack"><div v-for="job in data.jobs.slice(0,12)" :key="job.id" class="list-row admin-row"><div><h3>{{job.kind}}</h3><p>#{{job.id}} · meeting {{job.meeting_id}} · 尝试 {{job.attempt}}/{{job.max_attempts}}</p></div><span :class="['status',job.status==='failed'?'failed':job.status==='queued'?'warning':'']">{{job.status}}</span><span class="mono">{{fmt(job.created_at)}}</span></div></div></article>
      <article class="card"><header class="card-header"><div><div class="kicker">AI calls</div><h2>调用用途</h2></div></header><div v-if="!purposeStats.length" class="empty">尚无真实模型调用。无 API Key 时系统使用确定性降级。</div><div v-else class="purpose-bars"><div v-for="item in purposeStats" :key="item.purpose" class="purpose-bar"><div><strong>{{purposeLabel(item.purpose)}}</strong><span>{{item.calls}} 次 · {{item.success}} 成功</span></div><i :style="{ '--bar': `${Math.max(8, item.success / item.calls * 100)}%` }"/></div></div></article>
    </section>
  </section>

  <section v-else-if="section === 'models'" class="admin-stack">
    <article v-for="item in models" :key="item.purpose" class="card config-row"><div class="config-title"><div class="kicker">{{item.purpose}}</div><h2>{{purposeLabel(item.purpose)}}</h2><p>Provider：{{item.provider}}</p></div><div class="config-fields"><label>模型<input v-model="item.model"></label><label>Base URL<input v-model="item.base_url"></label><label class="toggle"><input v-model="item.enabled" type="checkbox"><span>启用</span></label><button class="button primary compact" :disabled="saving===`model-${item.purpose}`" @click="saveModel(item)"><Save :size="15"/>保存</button></div></article>
  </section>

  <section v-else-if="section === 'prompts'" class="admin-stack">
    <article v-for="item in prompts" :key="item.id" class="card prompt-card"><header class="card-header"><div><div class="kicker">{{item.purpose}} · V{{item.version}}</div><h2>{{item.name}}</h2></div><span :class="['status', item.enabled ? '' : 'neutral']">{{item.enabled?'active':'archived'}}</span></header><textarea v-model="item.template" rows="5"/><footer><span class="mono">{{fmt(item.created_at)}} · 新版本会保留历史记录</span><button class="button compact" :disabled="saving===`prompt-${item.id}`" @click="savePrompt(item)"><Save :size="15"/>发布新版本</button></footer></article>
  </section>

  <section v-else class="organization-grid">
    <article class="card"><header class="card-header"><div><div class="kicker">Departments</div><h2>部门</h2></div></header><div class="inline-form"><input v-model="newDepartment.name" placeholder="部门名称"><input v-model="newDepartment.code" placeholder="编码"><button class="button primary compact" @click="addDepartment">新增</button></div><div class="list-stack"><div v-for="item in departments" :key="item.id" class="list-row compact-row"><div><strong>{{item.name}}</strong><p>{{item.code}}</p></div><span class="status">{{item.enabled?'启用':'停用'}}</span></div></div></article>
    <article class="card"><header class="card-header"><div><div class="kicker">Employees</div><h2>员工账号</h2></div></header><div class="employee-form"><input v-model="newEmployee.username" placeholder="登录账号"><input v-model="newEmployee.display_name" placeholder="显示名称"><input v-model="newEmployee.password" type="password" placeholder="初始密码"><input v-model="newEmployee.title" placeholder="职位"><select v-model="newEmployee.department_id"><option value="">选择部门</option><option v-for="item in departments" :key="item.id" :value="String(item.id)">{{item.name}}</option></select><button class="button primary compact" @click="addEmployee">创建员工</button></div><div class="list-stack"><div v-for="item in employees" :key="item.id" class="list-row compact-row"><div><strong>{{item.display_name}}</strong><p>{{item.username}} · {{item.department_name||'未分配'}}</p></div><span :class="['status',item.enabled?'':'failed']">{{item.enabled?'启用':'停用'}}</span></div></div></article>
  </section>
</template>
