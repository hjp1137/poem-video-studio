import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import App from './App.vue'
import BatchCreateView from '@/views/BatchCreateView.vue'
import BatchListView from '@/views/BatchListView.vue'
import BatchDetailView from '@/views/BatchDetailView.vue'
import ServerOverviewView from '@/views/ServerOverviewView.vue'
import ServerGpuView from '@/views/ServerGpuView.vue'
import ServerServicesView from '@/views/ServerServicesView.vue'
import ServerOperationsView from '@/views/ServerOperationsView.vue'
import WorkflowTemplatesView from '@/views/WorkflowTemplatesView.vue'
import KeyframeTestView from '@/views/KeyframeTestView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'create', component: BatchCreateView },
    { path: '/batches', name: 'batches', component: BatchListView },
    { path: '/batches/:id', name: 'batch-detail', component: BatchDetailView },
    { path: '/workflows', name: 'workflow-templates', component: WorkflowTemplatesView },
    { path: '/keyframes', name: 'keyframes', component: KeyframeTestView },
    { path: '/server', name: 'server-overview', component: ServerOverviewView },
    { path: '/server/gpu', name: 'server-gpu', component: ServerGpuView },
    { path: '/server/services', name: 'server-services', component: ServerServicesView },
    { path: '/server/operations', name: 'server-operations', component: ServerOperationsView },
  ],
})

createApp(App).use(router).use(ElementPlus, { locale: zhCn }).mount('#app')
