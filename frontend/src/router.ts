import { createRouter, createWebHistory } from 'vue-router'
import { session } from './api'
import Login from './views/Login.vue'
import Dashboard from './views/Dashboard.vue'
import Meetings from './views/Meetings.vue'
import Meeting from './views/Meeting.vue'
import Transcript from './views/Transcript.vue'
import Minutes from './views/Minutes.vue'
import Review from './views/Review.vue'
import Admin from './views/Admin.vue'
import ModuleCenter from './views/ModuleCenter.vue'

const router = createRouter({
  history: createWebHistory('/minutestrace/'),
  routes: [
    { path: '/login', component: Login, meta: { public: true } },
    { path: '/', component: Dashboard },
    { path: '/meetings', component: Meetings },
    { path: '/meetings/:id', component: Meeting },
    { path: '/meetings/:id/transcript', component: Transcript },
    { path: '/meetings/:id/minutes', component: Minutes },
    { path: '/reviews/:id', component: Review },
    { path: '/admin', component: Admin },
    { path: '/meeting-center/management', component: Meetings, meta: { module: 'management' } },
    { path: '/meeting-center/materials', component: ModuleCenter, meta: { module: 'materials' } },
    { path: '/meeting-center/transcription', component: ModuleCenter, meta: { module: 'transcription' } },
    { path: '/meeting-center/minutes', component: ModuleCenter, meta: { module: 'minutes' } },
    { path: '/assistant/review', component: ModuleCenter, meta: { module: 'review' } },
    { path: '/assistant/observability', component: ModuleCenter, meta: { module: 'observability' } },
    { path: '/system/models', component: ModuleCenter, meta: { module: 'models' } },
    { path: '/system/prompts', component: ModuleCenter, meta: { module: 'prompts' } },
    { path: '/organization/departments', component: ModuleCenter, meta: { module: 'departments' } },
    { path: '/organization/employees', component: ModuleCenter, meta: { module: 'employees' } },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(to => {
  if (!to.meta.public && !session.token) return '/login'
  if (to.path === '/login' && session.token) return '/'
})

export default router
