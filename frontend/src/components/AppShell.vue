<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { LayoutDashboard, MessagesSquare, Activity, LogOut, Menu, X, Plus, Search } from '@lucide/vue'
import { session } from '../api'

const router = useRouter()
const mobileOpen = ref(false)
function logout() { session.clear(); router.push('/login') }
</script>

<template>
  <div class="app-frame">
    <header class="topbar">
      <RouterLink class="brand" to="/" aria-label="MinutesTrace 首页">
        <span class="brand-mark"><i/><i/><i/><i/></span>
        <span>MinutesTrace</span>
      </RouterLink>
      <button class="mobile-menu icon-btn" @click="mobileOpen = !mobileOpen" :aria-label="mobileOpen ? '关闭菜单' : '打开菜单'">
        <X v-if="mobileOpen" :size="20"/><Menu v-else :size="20"/>
      </button>
      <nav :class="['main-nav', { open: mobileOpen }]" @click="mobileOpen = false">
        <RouterLink to="/"><LayoutDashboard :size="17"/>工作台</RouterLink>
        <RouterLink to="/meetings"><MessagesSquare :size="17"/>会议</RouterLink>
        <RouterLink v-if="session.user?.role === 'admin'" to="/admin"><Activity :size="17"/>运行观测</RouterLink>
      </nav>
      <div class="top-actions">
        <button class="search-pill" @click="router.push('/meetings')"><Search :size="16"/>搜索会议</button>
        <button class="button primary compact" @click="router.push('/meetings?create=1')"><Plus :size="17"/>创建会议</button>
        <button class="avatar-button" @click="logout" :title="`${session.user?.display_name || '用户'} · 退出登录`">
          <span>{{ (session.user?.display_name || 'M').slice(0, 1) }}</span><LogOut :size="15"/>
        </button>
      </div>
    </header>
    <main class="page-wrap"><slot/></main>
    <footer class="app-footer">
      <span>MinutesTrace / 证据先于结论</span><span>Agent 修订由人确认</span>
    </footer>
  </div>
</template>
