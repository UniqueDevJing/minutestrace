<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, LockKeyhole } from '@lucide/vue'
import { api, session } from '../api'

const router = useRouter()
const username = ref('demo')
const password = ref('demo123456')
const busy = ref(false)
const error = ref('')

async function login() {
  busy.value = true; error.value = ''
  try {
    const result = await api('/auth/login', { method: 'POST', body: JSON.stringify({ username: username.value, password: password.value }) })
    session.token = result.token; session.user = result.user
    router.push('/')
  } catch (reason: any) { error.value = reason.message }
  finally { busy.value = false }
}
</script>

<template>
  <main class="login-page">
    <section class="login-story">
      <RouterLink class="brand" to="/login"><span class="brand-mark"><i/><i/><i/><i/></span><span>MinutesTrace</span></RouterLink>
      <div>
        <div class="eyebrow">Evidence-linked meeting intelligence</div>
        <h1>每个结论，<br>都能回到<em>当时。</em></h1>
        <p class="login-copy">转写不是终点。MinutesTrace 把会议决策、行动项和风险连接到原始片段，再让人决定 Agent 的修订是否生效。</p>
      </div>
      <div class="proof-strip">
        <div><strong>证据跳转</strong><span>结论直达转写时间</span></div>
        <div><strong>智能复核</strong><span>发现缺项和无证据结论</span></div>
        <div><strong>人工确认</strong><span>模型不覆盖正式纪要</span></div>
      </div>
    </section>
    <section class="login-panel">
      <form class="login-panel-inner" @submit.prevent="login">
        <div class="kicker">团队工作区</div>
        <h2>进入会议现场</h2>
        <p>演示账号已填入。登录后可完整体验证据化纪要流程。</p>
        <div v-if="error" class="notice error">{{ error }}</div>
        <div class="field"><label for="username">账号</label><input id="username" v-model="username" autocomplete="username" required></div>
        <div class="field"><label for="password">密码</label><input id="password" v-model="password" type="password" autocomplete="current-password" required minlength="8"></div>
        <button class="button primary" :disabled="busy"><LockKeyhole :size="17"/>{{ busy ? '正在验证…' : '进入工作区' }}<ArrowRight :size="17"/></button>
        <div class="demo-credentials"><span>demo / demo123456</span><span>数据为项目内置演示</span></div>
      </form>
    </section>
  </main>
</template>
