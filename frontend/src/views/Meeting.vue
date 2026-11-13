<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { UploadCloud, FileAudio, ArrowRight, WandSparkles, FileText, RefreshCw } from '@lucide/vue'
import { api } from '../api'

const route=useRoute(); const router=useRouter(); const id=Number(route.params.id)
const data=ref<any>(null); const busy=ref(''); const error=ref(''); const fileInput=ref<HTMLInputElement>()
let refreshTimer:number|undefined
async function load(){try{data.value=await api(`/meetings/${id}`)}catch(e:any){error.value=e.message}}
function scheduleRefresh(){
  window.clearTimeout(refreshTimer)
  if(data.value?.active_job && ['queued','running'].includes(data.value.active_job.status)){
    refreshTimer=window.setTimeout(async()=>{await load();scheduleRefresh()},2500)
  }
}
async function upload(file?:File){if(!file)return;busy.value='upload';error.value='';const body=new FormData();body.append('file',file);try{await api(`/meetings/${id}/assets`,{method:'POST',body});await load();scheduleRefresh()}catch(e:any){error.value=e.message}finally{busy.value=''}}
async function transcribe(assetId?:number){busy.value='transcribe';error.value='';try{await api(`/meetings/${id}/transcription${assetId?`?asset_id=${assetId}`:''}`,{method:'POST'});await load();scheduleRefresh()}catch(e:any){error.value=e.message}finally{busy.value=''}}
async function generate(){busy.value='minutes';error.value='';try{await api(`/meetings/${id}/minutes/generate`,{method:'POST'});await load();scheduleRefresh()}catch(e:any){error.value=e.message}finally{busy.value=''}}
const size=(n:number)=>n>1048576?`${(n/1048576).toFixed(1)} MB`:`${Math.ceil(n/1024)} KB`
const jobStatus=(v:string)=>({queued:'队列中',running:'处理中',succeeded:'已完成',failed:'失败'} as any)[v]||v
onMounted(async()=>{await load();scheduleRefresh()})
onUnmounted(()=>window.clearTimeout(refreshTimer))
</script>

<template>
  <div v-if="!data&&!error" class="loading">LOADING MEETING…</div><div v-else-if="error&&!data" class="notice error">{{error}}</div>
  <div v-else>
    <section class="detail-head"><div><div class="eyebrow">Meeting / {{data.id}}</div><h1>{{data.title}}</h1><p>{{data.agenda||'尚未填写会议议程。'}}</p></div><div class="detail-actions"><button class="button" @click="router.push(`/meetings/${id}/transcript`)">查看转写</button><button class="button primary" @click="router.push(`/meetings/${id}/minutes`)">打开纪要<ArrowRight :size="17"/></button></div></section>
    <div v-if="error" class="notice error" style="margin-bottom:16px">{{error}}</div>
    <div class="flow-rail"><div :class="['flow-step','done']"><span>01</span>会议资料</div><div :class="['flow-step',data.segment_count?'done':'active']"><span>02</span>语音转写</div><div :class="['flow-step',data.minutes_version?'done':data.segment_count?'active':'']"><span>03</span>生成纪要</div><div :class="['flow-step',data.minutes_status==='approved'?'done':data.minutes_version?'active':'']"><span>04</span>人工确认</div></div>
    <section class="grid two">
      <article class="card paper"><header class="card-header"><div><div class="kicker">Source</div><h2>会议资料</h2></div><FileAudio :size="23"/></header><input ref="fileInput" type="file" hidden accept="audio/*,video/*,.txt,.md,.srt,.vtt" @change="upload(($event.target as HTMLInputElement).files?.[0])"><button class="upload-zone" style="width:100%" @click="fileInput?.click()"><span><UploadCloud :size="30"/><strong style="display:block;margin:12px 0 5px">上传录音或转写文本</strong><small>支持音视频、TXT、Markdown、SRT、VTT · 最大 512 MB</small></span></button><div class="file-list"><div v-for="file in data.assets" :key="file.id" class="file-item"><span>{{file.file_name}} · {{size(file.size_bytes)}}</span><button class="button compact" :disabled="!!busy" @click="transcribe(file.id)">{{busy==='transcribe'?'已提交':'开始转写'}}</button></div></div></article>
      <article class="card"><header class="card-header"><div><div class="kicker">Pipeline</div><h2>处理状态</h2></div><RefreshCw :size="21" @click="load" style="cursor:pointer"/></header><div v-if="data.active_job" class="notice" style="margin-bottom:16px">{{jobStatus(data.active_job.status)}} · {{data.active_job.progress}}%<br><span v-if="data.active_job.error">{{data.active_job.error}}</span></div><div class="grid two"><div class="card paper stat-card" style="min-height:140px"><span class="eyebrow">转写片段</span><strong>{{data.segment_count}}</strong></div><div class="card paper stat-card" style="min-height:140px"><span class="eyebrow">纪要版本</span><strong>{{data.minutes_version?`V${data.minutes_version}`:'—'}}</strong></div></div><div style="display:grid;gap:9px;margin-top:16px"><button class="button" :disabled="!!busy||!data.assets.length" @click="transcribe()"><WandSparkles :size="17"/>提交转写任务</button><button class="button primary" :disabled="!!busy||!data.segment_count" @click="generate"><FileText :size="17"/>{{busy==='minutes'?'已提交':'生成证据化纪要'}}</button></div></article>
    </section>
    <section class="card dark" style="margin-top:16px"><div class="grid three"><div><div class="kicker" style="color:#9fc9cb">Participants</div><h3>{{data.participants.join(' · ')||'待补充参会人'}}</h3></div><div><div class="kicker" style="color:#9fc9cb">Start</div><h3>{{new Date(data.starts_at).toLocaleString('zh-CN')}}</h3></div><div><div class="kicker" style="color:#9fc9cb">Control</div><h3>Agent 修订需人工批准</h3></div></div></section>
  </div>
</template>
