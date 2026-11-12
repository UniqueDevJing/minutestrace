<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Check, X, StopCircle, ShieldCheck, Bot } from '@lucide/vue'
import { api } from '../api'
const route=useRoute();const router=useRouter();const id=Number(route.params.id)
const run=ref<any>(null);const error=ref('');const busy=ref('');let timer:number;let events: EventSource | null = null
async function load(){try{run.value=await api(`/review-runs/${id}`)}catch(e:any){error.value=e.message}}
async function connect(){
  events?.close()
  if(!run.value||!['queued','running'].includes(run.value.status))return
  try {
    const stream=await api<{ticket:string}>(`/review-runs/${id}/events-ticket`,{method:'POST'})
    events=new EventSource(`/minutestrace/api/review-runs/${id}/events?ticket=${encodeURIComponent(stream.ticket)}`)
  } catch(e:any) { error.value=e.message; return }
  events.addEventListener('run', event=>{
    try { run.value=JSON.parse((event as MessageEvent).data); if(!['queued','running'].includes(run.value.status))events?.close() } catch { /* keep the last valid run */ }
  })
  events.onerror=()=>{events?.close();timer=window.setTimeout(async()=>{await load();connect()},2000)}
}
async function decide(action:'approve'|'reject'|'cancel'|'resume'){
  busy.value=action
  try{run.value=await api(`/review-runs/${id}/${action}`,{method:'POST',body:JSON.stringify({reason:action==='approve'?'人工确认修订稿':action==='resume'?'继续未完成的审校':'人工要求保留原版本'})});if(action==='resume')connect()}catch(e:any){error.value=e.message}finally{busy.value=''}
}
const statusText=(v:string)=>({queued:'排队中',running:'Agent 正在复核',waiting_human:'等待人工确认',approved:'已批准',rejected:'已驳回',cancelled:'已取消',failed:'运行失败'} as any)[v]||v
onMounted(async()=>{await load();connect()});onUnmounted(()=>{clearTimeout(timer);events?.close()})
</script>
<template><div v-if="!run&&!error" class="loading">CONNECTING AGENT RUN…</div><div v-else-if="error&&!run" class="notice error">{{error}}</div><div v-else><section class="page-heading"><div><button class="button compact" @click="router.push(`/meetings/${run.meeting_id}/minutes`)"><ArrowLeft :size="16"/>返回纪要</button><div class="eyebrow" style="margin-top:24px">Agent run / {{run.id}}</div><h1>先审查，再修订。<br>最后由你确认。</h1></div><span :class="['status',run.status==='failed'?'failed':run.status==='waiting_human'?'warning':'']">{{statusText(run.status)}}</span></section><div v-if="error" class="notice error" style="margin-bottom:16px">{{error}}</div><div class="run-layout"><aside><article class="card"><div class="kicker">Quality score</div><div class="run-score">{{Math.round(run.score)}}</div><p>基于证据完整性、行动项可落实性和结构缺失计算。</p></article><article class="card dark" style="margin-top:16px"><ShieldCheck :size="26"/><h3 style="margin-top:20px">人类控制边界</h3><p>Agent 只生成候选修订稿。批准操作才会创建新的正式版本。</p></article></aside><main><article class="card paper"><header class="card-header"><div><div class="kicker">Execution trace / SSE</div><h2>运行轨迹</h2></div><Bot :size="25"/></header><div v-if="!run.steps.length" class="notice">运行已进入队列，等待工作进程领取。</div><div v-else class="timeline"><div v-for="step in run.steps" :key="step.id" class="timeline-step"><h3>{{step.node==='audit'?'审查纪要':'生成修订稿'}}</h3><p>{{step.summary}} · {{step.duration_ms}} ms</p></div></div></article><article v-if="run.revised&&Object.keys(run.revised).length" class="card paper" style="margin-top:16px"><header class="card-header"><div><div class="kicker">Candidate revision</div><h2>候选修订摘要</h2></div><span class="tag">仅供人工确认</span></header><p>{{run.revised.summary}}</p><div class="revision-grid"><div><strong>{{run.revised.decisions?.length||0}}</strong><span>决策</span></div><div><strong>{{run.revised.action_items?.length||0}}</strong><span>行动项</span></div><div><strong>{{run.revised.risks?.length||0}}</strong><span>风险</span></div></div></article><article class="card" style="margin-top:16px"><header class="card-header"><div><div class="kicker">Findings</div><h2>问题清单</h2></div><span class="tag">{{run.issues.length}} issues</span></header><div v-if="!run.issues.length" class="notice">暂未发现结构化问题。</div><div v-else class="issue-list"><div v-for="(issue,index) in run.issues" :key="index" class="issue"><strong>{{issue.field}} / {{issue.severity}}</strong><span>{{issue.message}}</span></div></div></article><div v-if="['queued','running'].includes(run.status)" class="decision-bar"><div><strong>Agent 正在运行</strong><p>状态通过 SSE 持久化推送，离开页面不会中断任务。</p></div><div class="actions"><button class="button danger compact" :disabled="!!busy" @click="decide('cancel')"><StopCircle :size="15"/>取消</button></div></div><div v-else-if="run.status==='waiting_human'" class="decision-bar"><div><strong>修订稿等待确认</strong><p>批准会创建新版本；驳回会保留当前正式纪要。</p></div><div class="actions"><button class="button compact" style="color:white" :disabled="!!busy" @click="decide('reject')"><X :size="15"/>驳回</button><button class="button primary compact" :disabled="!!busy" @click="decide('approve')"><Check :size="15"/>批准修订</button></div></div><div v-else-if="['cancelled','failed'].includes(run.status)" class="decision-bar"><div><strong>运行可以恢复</strong><p>系统会从已保存的轮次和候选修订继续。</p></div><div class="actions"><button class="button primary compact" :disabled="!!busy" @click="decide('resume')"><Bot :size="15"/>恢复运行</button></div></div></main></div></div></template>
