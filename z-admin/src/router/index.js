import { createRouter, createWebHashHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import SettingsView from '../views/settings/SettingsView.vue'
import ProjectDetailView from '../views/project/ProjectDetailView.vue'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: HomeView,
  },
  {
    path: '/projects/:id',
    redirect: to => `/projects/${to.params.id}/content`,
  },
  {
    path: '/projects/:id/content',
    name: 'ProjectContent',
    component: ProjectDetailView,
  },
  {
    path: '/projects/:id/assets',
    name: 'ProjectAssets',
    component: ProjectDetailView,
  },
  {
    path: '/projects/:id/workshop',
    name: 'ProjectWorkshop',
    component: ProjectDetailView,
  },
  {
    path: '/projects/:id/workshop/:episodeId',
    name: 'ProjectEpisodeDetail',
    component: ProjectDetailView,
  },
  {
    path: '/projects/:id/jobs',
    name: 'ProjectJobs',
    component: ProjectDetailView,
  },
  {
    path: '/settings',
    name: 'Settings',
    component: SettingsView,
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

export default router
