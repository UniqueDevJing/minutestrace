<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowUpRight, Plus, CheckCircle2, Clock3 } from '@lucide/vue'
import { api, session } from '../api'

const router = useRouter()
const data = ref<any>(null)
const error = ref('')
onMounted(async () => { try { data.value = await api('/dashboard') } catch (e: any) { error.value = e.message } })
const fmt = (value: string) => new Date(value).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
const statusText = (value: string) => ({ ended: '已结束', draft: '草稿', scheduled: '待开始', live: '进行中', archived: '已归档' } as any)[value] || value
</script>

<template>
  <div v-if="!data && !error" class="loading">LOADING WORKSPACE…</div>
  <div v-else-if="error" class="notice error">{{ error }}</div>
  <div v-else>
    <section class="workspace-hero">
      <article class="card lead">
        <div><div class="eyebrow">{{ new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }) }}</div><h1>{{ session.user?.display_name }}，<br>先看需要确认的结论。</h1></div>
        <div><button class="button primary" @click="router.push('/meetings?create=1')"><Plus :size="18"/>创建会议</button></div>
      </article>
      <article class="card trace-visual">
        <div><div class="kicker" style="color:#a9cacc">Trace coverage</div><h2>证据链正在工作</h2><p>转写片段为纪要结论提供可复查的来源。</p></div>
        <div class="trace-lines">
          <div class="trace-line"><span>DECISION</span><i style="--width:86%"/></div>
          <div class="trace-line"><span>ACTION</span><i style="--width:72%"/></div>
          <div class="trace-line"><span>RISK</span><i style="--width:61%"/></div>
        </div>
      </article>
    </section>
    <section class="grid four" style="margin-bottom:16px">
      <article class="card stat-card"><div class="dot"/><div><span class="eyebrow">全部会议</span><strong>{{ data.stats.meetings }}</strong></div></article>
      <article class="card stat-card"><div class="dot"/><div><span class="eyebrow">待人工确认</span><strong>{{ data.stats.pending_reviews }}</strong></div></article>
      <article class="card stat-card"><div class="dot"/><div><span class="eyebrow">开放行动项</span><strong>{{ data.stats.open_actions }}</strong></div></article>
      <article class="card stat-card dark"><div class="dot"/><div><span class="eyebrow" style="color:#9fc9cb">证据片段</span><strong>{{ data.stats.evidence_segments }}</strong></div></article>
    </section>
    <section class="grid two">
      <article class="card paper">
        <header class="card-header"><div><div class="kicker">Recent meetings</div><h2>最近会议</h2></div><button class="icon-btn" @click="router.push('/meetings')"><ArrowUpRight :size="18"/></button></header>
        <div class="list-stack">
          <div v-for="meeting in data.meetings" :key="meeting.id" class="list-row" @click="router.push(`/meetings/${meeting.id}`)" style="cursor:pointer">
            <div><h3>{{ meeting.title }}</h3><p>{{ meeting.participants.join(' · ') || '尚未添加参会人' }}</p></div>
            <span class="mono" style="font-size:12px">{{ fmt(meeting.starts_at) }}</span>
            <span :class="['status', meeting.status === 'draft' ? 'neutral' : '']">{{ statusText(meeting.status) }}</span>
            <ArrowUpRight :size="17"/>
          </div>
        </div>
      </article>
      <article class="card">
        <header class="card-header"><div><div class="kicker">Open actions</div><h2>行动项</h2></div><CheckCircle2 :size="23"/></header>
        <div v-if="!data.actions.length" class="empty">当前没有开放行动项</div>
        <div v-else class="list-stack">
          <div v-for="item in data.actions" :key="item.id" class="list-row" style="grid-template-columns:1fr .5fr auto; cursor:pointer" @click="router.push(`/meetings/${item.meeting_id}/minutes`)">
            <div><h3>{{ item.title }}</h3><p>{{ item.owner }}</p></div>
            <span class="tag"><Clock3 :size="11" style="vertical-align:-2px"/> {{ item.due }}</span><ArrowUpRight :size="17"/>
          </div>
        </div>
      </article>
    </section>
  </div>
</template>
