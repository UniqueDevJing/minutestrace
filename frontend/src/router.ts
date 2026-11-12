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
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(to => {
  if (!to.meta.public && !session.token) return '/login'
  if (to.path === '/login' && session.token) return '/'
})

export default router
