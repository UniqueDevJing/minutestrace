<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { LayoutDashboard, MessagesSquare, Activity, Menu, X, Plus, Search, ClipboardCheck, Settings2, HelpCircle, ChevronDown, FileAudio, FileText, Bot, SlidersHorizontal, Building2, Users, Home } from '@lucide/vue'
import { session } from '../api'

const router = useRouter()
const mobileOpen = ref(false)
const sectionTitles: Record<string, string> = {
  '/meeting-center/management': '会议管理', '/meeting-center/materials': '会议资料', '/meeting-center/transcription': '转写任务', '/meeting-center/minutes': 'AI会议纪要',
  '/assistant/review': '纪要自检', '/assistant/observability': '运行观测', '/system/models': 'AI模型配置', '/system/prompts': 'Prompt模板',
  '/organization/departments': '部门管理', '/organization/employees': '员工账号管理', '/admin': '运行观测', '/meetings': '会议管理',
}
const currentSectionTitle = () => sectionTitles[router.currentRoute.value.path] || (router.currentRoute.value.path === '/' ? '数据总览' : '会议空间')
function logout() { session.clear(); router.push('/login') }
</script>

<template>
  <div class="app-frame product-shell">
    <aside :class="['side-rail', { open: mobileOpen }]">
      <RouterLink class="brand" to="/" aria-label="MinutesTrace 首页">
        <span class="brand-mark"><i/><i/><i/><i/></span>
        <span class="brand-copy"><strong>MinutesTrace</strong><small>Evidence workspace</small></span>
      </RouterLink>
      <div class="rail-caption">主工作台</div>
      <nav class="rail-nav" @click="mobileOpen = false">
        <RouterLink to="/"><Home :size="17"/>系统首页</RouterLink>
        <RouterLink to="/meeting-center/management"><MessagesSquare :size="17"/>会议管理</RouterLink>
      </nav>
      <div class="rail-caption">会议中心</div>
      <nav class="rail-nav" @click="mobileOpen = false">
        <RouterLink to="/meeting-center/materials"><FileText :size="17"/>会议资料</RouterLink>
        <RouterLink to="/meeting-center/transcription"><FileAudio :size="17"/>转写任务</RouterLink>
        <RouterLink to="/meeting-center/minutes"><ClipboardCheck :size="17"/>AI会议纪要</RouterLink>
      </nav>
      <div class="rail-caption">智能助手</div>
      <nav class="rail-nav" @click="mobileOpen = false">
        <RouterLink to="/assistant/review"><Bot :size="17"/>纪要自检</RouterLink>
        <RouterLink to="/assistant/observability"><Activity :size="17"/>运行观测</RouterLink>
      </nav>
      <div class="rail-caption">系统配置</div>
      <nav class="rail-nav" @click="mobileOpen = false">
        <RouterLink to="/system/models"><Settings2 :size="17"/>AI模型配置</RouterLink>
        <RouterLink to="/system/prompts"><SlidersHorizontal :size="17"/>Prompt模板</RouterLink>
      </nav>
      <div v-if="session.user?.role === 'admin'" class="rail-caption">组织与员工</div>
      <nav v-if="session.user?.role === 'admin'" class="rail-nav" @click="mobileOpen = false">
        <RouterLink to="/organization/departments"><Building2 :size="17"/>部门管理</RouterLink>
        <RouterLink to="/organization/employees"><Users :size="17"/>员工账号管理</RouterLink>
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
        <div class="breadcrumb"><span>AI协作平台</span><b>/</b><strong>{{ currentSectionTitle() }}</strong></div>
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
