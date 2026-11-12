<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowUpRight, Plus, CheckCircle2, Clock3, CalendarDays, Filter, Sparkles, FileCheck2 } from '@lucide/vue'
import { api, session } from '../api'

const router = useRouter()
const data = ref<any>(null)
const error = ref('')
const range = ref('近 30 天')

onMounted(async () => { try { data.value = await api('/dashboard') } catch (e: any) { error.value = e.message } })
const fmt = (value: string) => new Date(value).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
const statusText = (value: string) => ({ ended: '已完成', draft: '草稿', scheduled: '待开始', live: '进行中', archived: '已归档' } as any)[value] || value
const analytics = computed(() => data.value?.analytics || { meeting_trend: [], meeting_status: [], review_status: [], ai: {} })
const trend = computed(() => analytics.value.meeting_trend || [])
const maxTrend = computed(() => Math.max(1, ...trend.value.map((item: any) => item.value)))
const trendPoints = computed(() => trend.value.map((item: any, index: number) => { const x = trend.value.length <= 1 ? 0 : (index / (trend.value.length - 1)) * 100; const y = 88 - (item.value / maxTrend.value) * 68; return `${x},${y}` }).join(' '))
const trendArea = computed(() => trendPoints.value ? `0,100 ${trendPoints.value} 100,100` : '')
const totalStatus = (items: any[]) => Math.max(1, items.reduce((sum, item) => sum + item.value, 0))
const donutStyle = (items: any[], colors: string[]) => { let cursor = 0; const total = totalStatus(items); const stops = items.map((item, index) => { const start = cursor; cursor += (item.value / total) * 100; return `${colors[index % colors.length]} ${start}% ${cursor}%` }); return { background: `conic-gradient(${stops.join(', ')})` } }
const statusColors = ['#3568f5', '#35b77a', '#f2b441', '#ec6a5d']
const reviewColors = ['#35b77a', '#f2b441', '#ec6a5d']
</script>

<template>
  <div v-if="!data && !error" class="loading">LOADING WORKSPACE…</div>
  <div v-else-if="error" class="notice error">{{ error }}</div>
  <div v-else class="dashboard-page">
    <section class="dashboard-heading"><div><div class="kicker">Meeting intelligence / overview</div><h1>会议数据总览</h1><p>把转写、纪要、Agent 自检与行动项放在同一张运营视图里。</p></div><div class="dashboard-heading-actions"><button class="button" @click="router.push('/meetings')"><FileCheck2 :size="16"/>查看会议</button><button class="button primary" @click="router.push('/meetings?create=1')"><Plus :size="17"/>新建会议</button></div></section>
    <section class="dashboard-filter" aria-label="数据筛选"><div class="filter-item"><CalendarDays :size="16"/><span>数据范围</span><strong>{{ range }}</strong></div><div class="filter-item"><Filter :size="16"/><span>会议状态</span><strong>全部状态</strong></div><div class="filter-spacer"/><span class="data-freshness"><span class="pulse-dot"/>数据已同步 · 刚刚</span></section>
    <section class="metric-grid">
      <article class="metric-card metric-blue"><div class="metric-icon"><CalendarDays :size="17"/></div><div><span>会议总数</span><strong>{{ data.stats.meetings }}</strong><small>当前工作区累计</small></div><b>+{{ Math.max(0, analytics.meeting_growth || 0) }}%</b></article>
      <article class="metric-card metric-green"><div class="metric-icon"><CheckCircle2 :size="17"/></div><div><span>纪要完成率</span><strong>{{ analytics.minutes_completion_rate || 100 }}<em>%</em></strong><small>已生成结构化纪要</small></div><b>稳定</b></article>
      <article class="metric-card metric-orange"><div class="metric-icon"><Sparkles :size="17"/></div><div><span>Token 使用量</span><strong>{{ (analytics.ai?.token_total || 0).toLocaleString() }}</strong><small>输入 + 输出 Token</small></div><b>{{ analytics.ai?.calls || 0 }} 次</b></article>
      <article class="metric-card metric-purple"><div class="metric-icon"><Clock3 :size="17"/></div><div><span>平均 AI 响应</span><strong>{{ analytics.ai?.avg_latency_ms || 0 }}<em>ms</em></strong><small>模型调用平均耗时</small></div><b>{{ analytics.ai?.success_rate || 100 }}% 成功</b></article>
    </section>
    <section class="analytics-grid">
      <article class="analytics-card trend-card"><header class="analytics-card-header"><div><span class="kicker">AI usage</span><h2>AI 调用与 Token 趋势</h2></div><span class="chart-legend"><i class="legend-line"/>调用次数 <i class="legend-bar"/>Token</span></header><div class="line-chart" aria-label="近七日会议趋势折线图"><div class="chart-y"><span>{{ maxTrend }}</span><span>{{ Math.ceil(Number(maxTrend) / 2) }}</span><span>0</span></div><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img"><defs><linearGradient id="trendFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#3568f5" stop-opacity=".24"/><stop offset="1" stop-color="#3568f5" stop-opacity="0"/></linearGradient></defs><path v-if="trendArea" :d="`M ${trendArea.replaceAll(' ', ' L ')}`" fill="url(#trendFill)"/><polyline v-if="trendPoints" :points="trendPoints" fill="none" stroke="#3568f5" stroke-width="1.8" vector-effect="non-scaling-stroke"/><circle v-for="(item, index) in trend" :key="item.label" :cx="trend.length <= 1 ? 0 : (Number(index) / (trend.length - 1)) * 100" :cy="88 - (Number(item.value) / Number(maxTrend)) * 68" r="1.8" fill="#fff" stroke="#3568f5" stroke-width="1.4" vector-effect="non-scaling-stroke"/></svg><div class="chart-x"><span v-for="item in trend" :key="item.label">{{ item.label }}</span></div></div></article>
      <article class="analytics-card donut-card"><header class="analytics-card-header"><div><span class="kicker">Meeting mix</span><h2>会议状态分布</h2></div><button class="icon-btn light" @click="router.push('/meetings')"><ArrowUpRight :size="17"/></button></header><div class="donut-layout"><div class="donut" :style="donutStyle(analytics.meeting_status, statusColors)"><div><strong>{{ data.stats.meetings }}</strong><span>场会议</span></div></div><div class="donut-legend"><div v-for="(item, index) in analytics.meeting_status" :key="item.label"><i :style="{ background: statusColors[Number(index) % statusColors.length] }"/><span>{{ item.label }}</span><strong>{{ item.value }}</strong></div></div></div></article>
      <article class="analytics-card donut-card"><header class="analytics-card-header"><div><span class="kicker">Review pipeline</span><h2>纪要审核状态</h2></div><button class="icon-btn light" @click="router.push('/meetings')"><ArrowUpRight :size="17"/></button></header><div class="donut-layout"><div class="donut" :style="donutStyle(analytics.review_status, reviewColors)"><div><strong>{{ analytics.review_total || 0 }}</strong><span>份纪要</span></div></div><div class="donut-legend"><div v-for="(item, index) in analytics.review_status" :key="item.label"><i :style="{ background: reviewColors[Number(index) % reviewColors.length] }"/><span>{{ item.label }}</span><strong>{{ item.value }}</strong></div></div></div></article>
    </section>
    <section class="dashboard-bottom"><article class="analytics-card list-card"><header class="analytics-card-header"><div><span class="kicker">Recent meetings</span><h2>最近会议</h2></div><button class="text-link" @click="router.push('/meetings')">查看全部 <ArrowUpRight :size="14"/></button></header><div class="meeting-list"><div v-for="meeting in data.meetings" :key="meeting.id" class="meeting-list-row" @click="router.push(`/meetings/${meeting.id}`)"><span class="meeting-index">{{ String(meeting.id).padStart(2, '0') }}</span><div><strong>{{ meeting.title }}</strong><small>{{ meeting.participants.join(' · ') || '尚未添加参会人' }}</small></div><span class="meeting-date">{{ fmt(meeting.starts_at) }}</span><span :class="['status light-status', meeting.status === 'draft' ? 'neutral' : '']">{{ statusText(meeting.status) }}</span><ArrowUpRight :size="16"/></div></div></article><article class="analytics-card list-card action-card"><header class="analytics-card-header"><div><span class="kicker">Open actions</span><h2>待跟进行动项</h2></div><CheckCircle2 :size="20" class="header-icon"/></header><div v-if="!data.actions.length" class="empty compact-empty">当前没有开放行动项</div><div v-else class="action-list"><div v-for="item in data.actions" :key="item.id" class="action-row" @click="router.push(`/meetings/${item.meeting_id}/minutes`)"><span class="action-check"/><div><strong>{{ item.title }}</strong><small>{{ item.owner || '待确认' }}</small></div><span class="action-due"><Clock3 :size="12"/>{{ item.due }}</span></div></div></article></section>
  </div>
</template>
