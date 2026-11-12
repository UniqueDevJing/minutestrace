<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus, Search, X, ArrowUpRight } from '@lucide/vue'
import { api } from '../api'

const route = useRoute(); const router = useRouter()
const meetings = ref<any[]>([]); const query = ref(''); const busy = ref(false); const error = ref('')
const modal = ref(route.query.create === '1')
const form = reactive({ title: '', starts_at: new Date(Date.now() + 3600000).toISOString().slice(0, 16), participants: '', agenda: '' })
async function load() { busy.value = true; try { meetings.value = (await api(`/meetings?query=${encodeURIComponent(query.value)}`)).items } catch(e:any) { error.value=e.message } finally {busy.value=false} }
async function create() { busy.value = true; error.value=''; try { const item = await api('/meetings', { method:'POST', body: JSON.stringify({ title: form.title, starts_at: new Date(form.starts_at).toISOString(), participants: form.participants.split(/[，,]/).map(v=>v.trim()).filter(Boolean), agenda: form.agenda }) }); modal.value=false; router.push(`/meetings/${item.id}`) } catch(e:any) { error.value=e.message } finally {busy.value=false} }
let timer:number; watch(query, () => { clearTimeout(timer); timer=window.setTimeout(load, 250) })
onMounted(load)
const fmt=(v:string)=>new Date(v).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})
</script>

<template>
  <section class="page-heading"><div><div class="eyebrow">Meeting archive</div><h1>会议不是文件夹，<br>是可以追溯的决定。</h1><p>从资料进入到正式纪要，每一步都有明确状态。</p></div><button class="button primary" @click="modal=true"><Plus :size="18"/>创建会议</button></section>
  <div class="card paper" style="margin-bottom:16px; padding:14px 18px; display:flex; align-items:center; gap:10px"><Search :size="18"/><input v-model="query" placeholder="按会议名称搜索" style="flex:1;border:0;background:transparent;outline:0"></div>
  <div v-if="error" class="notice error" style="margin-bottom:16px">{{ error }}</div>
  <div v-if="busy && !meetings.length" class="loading">LOADING MEETINGS…</div>
  <div v-else-if="!meetings.length" class="empty">没有匹配的会议</div>
  <div v-else class="table-wrap"><table><thead><tr><th>会议</th><th>时间</th><th>参会人</th><th>证据片段</th><th>纪要</th><th></th></tr></thead><tbody><tr v-for="item in meetings" :key="item.id" class="clickable" @click="router.push(`/meetings/${item.id}`)"><td><span class="table-title">{{item.title}}</span><br><span class="status neutral" style="margin-top:7px">{{item.status}}</span></td><td class="mono">{{fmt(item.starts_at)}}</td><td>{{item.participants.slice(0,3).join(' · ')||'—'}}</td><td>{{item.segment_count}}</td><td>{{item.minutes_version ? `V${item.minutes_version} · ${item.minutes_status}` : '待生成'}}</td><td><ArrowUpRight :size="17"/></td></tr></tbody></table></div>
  <div v-if="modal" class="modal-backdrop" @click.self="modal=false"><form class="modal" @submit.prevent="create"><header class="card-header"><div><div class="kicker">New meeting</div><h2>创建会议</h2></div><button type="button" class="icon-btn" @click="modal=false"><X :size="18"/></button></header><div v-if="error" class="notice error" style="margin-bottom:16px">{{error}}</div><div class="form-grid"><div class="field full"><label>会议名称</label><input v-model="form.title" required minlength="2" placeholder="例如：版本发布评审"></div><div class="field"><label>开始时间</label><input v-model="form.starts_at" type="datetime-local" required></div><div class="field"><label>参会人</label><input v-model="form.participants" placeholder="林澄，周岚，陈舟"></div><div class="field full"><label>议程</label><textarea v-model="form.agenda" placeholder="本次会议需要确认的问题"></textarea></div></div><div class="form-actions"><button type="button" class="button" @click="modal=false">取消</button><button class="button primary" :disabled="busy">{{busy?'正在创建…':'创建并进入'}}</button></div></form></div>
</template>
