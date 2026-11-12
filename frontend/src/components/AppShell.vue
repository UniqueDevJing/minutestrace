<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { LayoutDashboard, MessagesSquare, Activity, LogOut, Menu, X, Plus, Search, ClipboardCheck, Settings2, HelpCircle, ChevronDown } from '@lucide/vue'
import { session } from '../api'

const router = useRouter()
const mobileOpen = ref(false)
function logout() { session.clear(); router.push('/login') }
</script>

<template>
  <div class="app-frame product-shell">
    <aside :class="['side-rail', { open: mobileOpen }]">
      <RouterLink class="brand" to="/" aria-label="MinutesTrace 首页">
        <span class="brand-mark"><i/><i/><i/><i/></span>
        <span>MinutesTrace</span>
      </RouterLink>
      <div class="rail-caption">工作台</div>
      <nav class="rail-nav" @click="mobileOpen = false">
        <RouterLink to="/"><LayoutDashboard :size="17"/>总览</RouterLink>
        <RouterLink to="/meetings"><MessagesSquare :size="17"/>会议管理</RouterLink>
        <RouterLink to="/meetings"><ClipboardCheck :size="17"/>纪要回顾</RouterLink>
      </nav>
      <div class="rail-caption">智能能力</div>
      <nav class="rail-nav" @click="mobileOpen = false">
        <RouterLink to="/admin" v-if="session.user?.role === 'admin'"><Activity :size="17"/>运行观测</RouterLink>
        <RouterLink to="/meetings"><Settings2 :size="17"/>模型与提示词</RouterLink>
      </nav>
      <div class="rail-spacer"/>
      <button class="rail-support" @click="router.push('/meetings')"><HelpCircle :size="17"/><span>需要帮助？</span></button>
      <button class="rail-user" @click="logout" :title="`${session.user?.display_name || '用户'} · 退出登录`">
        <span class="avatar">{{ (session.user?.display_name || 'M').slice(0, 1) }}</span>
        <span class="rail-user-copy"><strong>{{ session.user?.display_name || '用户' }}</strong><small>{{ session.user?.role === 'admin' ? '管理员' : '成员' }}</small></span>
        <ChevronDown :size="15"/>
      </button>
    </aside>
    <div class="shell-main">
      <header class="topbar">
        <button class="mobile-menu icon-btn" @click="mobileOpen = !mobileOpen" :aria-label="mobileOpen ? '关闭菜单' : '打开菜单'">
          <X v-if="mobileOpen" :size="20"/><Menu v-else :size="20"/>
        </button>
        <div class="breadcrumb"><span>工作台</span><b>/</b><strong>{{ router.currentRoute.value.path === '/' ? '数据总览' : '会议空间' }}</strong></div>
        <div class="top-actions">
          <button class="search-pill" @click="router.push('/meetings')"><Search :size="16"/><span>搜索会议</span><kbd>⌘ K</kbd></button>
          <button class="button primary compact" @click="router.push('/meetings?create=1')"><Plus :size="17"/>新建会议</button>
        </div>
      </header>
      <main class="page-wrap"><slot/></main>
      <footer class="app-footer">
        <span>MinutesTrace <i/> 证据先于结论</span><span>Agent 修订由人确认</span>
      </footer>
    </div>
  </div>
</template>
