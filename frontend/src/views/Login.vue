<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, LockKeyhole } from '@lucide/vue'
import { api, session } from '../api'

const router = useRouter()
const isDev = import.meta.env.DEV
const username = ref(isDev ? 'demo' : '')
const password = ref(isDev ? 'demo123456' : '')
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
        <div class="eyebrow">会议记录工作台</div>
        <h1>把会议里的决定，<br>留给<em>下一步。</em></h1>
        <p class="login-copy">MinutesTrace 把录音、转写、正式纪要和行动项放在同一个工作区。每条结论都能回到原始片段，最后由人确认。</p>
      </div>
      <div class="proof-strip">
        <div><strong>证据跳转</strong><span>结论直达转写时间</span></div>
        <div><strong>复核提醒</strong><span>发现缺项和无证据结论</span></div>
        <div><strong>人工确认</strong><span>模型不覆盖正式纪要</span></div>
      </div>
    </section>
    <section class="login-panel">
      <form class="login-panel-inner" @submit.prevent="login">
        <div class="kicker">团队工作区</div>
        <h2>进入工作区</h2>
        <p>登录后查看会议资料、正式纪要和待跟进行动项。</p>
        <div v-if="error" class="notice error">{{ error }}</div>
        <div class="field"><label for="username">账号</label><input id="username" v-model="username" autocomplete="username" required></div>
        <div class="field"><label for="password">密码</label><input id="password" v-model="password" type="password" autocomplete="current-password" required minlength="8"></div>
        <button class="button primary" :disabled="busy"><LockKeyhole :size="17"/>{{ busy ? '正在验证…' : '进入工作区' }}<ArrowRight :size="17"/></button>
        <div v-if="isDev" class="demo-credentials"><span>demo / demo123456</span><span>仅开发环境演示账号</span></div>
      </form>
    </section>
  </main>
</template>
