<template>
  <el-container class="app-shell">
    <el-header class="app-header" height="56px">
      <div class="brand">
        <span class="brand-title">诗影工坊</span>
        <span class="brand-sub">PoemVideo Studio · 整首诗一次输入,一键排队生成</span>
      </div>
      <nav class="nav">
        <router-link to="/" class="nav-link">新建批量任务</router-link>
        <router-link to="/batches" class="nav-link">批次列表</router-link>
        <router-link to="/workflows" class="nav-link">模板管理</router-link>
        <span class="nav-sep">|</span>
        <router-link to="/server" class="nav-link">服务器总览</router-link>
        <router-link to="/server/gpu" class="nav-link">GPU</router-link>
        <router-link to="/server/services" class="nav-link">模型服务</router-link>
        <router-link to="/server/operations" class="nav-link">操作日志</router-link>
      </nav>
    </el-header>
    <el-main class="app-main">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup lang="ts"></script>

<style>
html,
body,
#app {
  height: 100%;
  margin: 0;
}
body {
  font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Microsoft YaHei', Arial, sans-serif;
  background: #f5f7fa;
}
.app-shell {
  min-height: 100%;
}
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #1f2d3d;
  color: #fff;
  padding: 0 24px;
}
.brand-title {
  font-size: 18px;
  font-weight: 600;
  margin-right: 12px;
}
.brand-sub {
  font-size: 12px;
  color: #aeb8c4;
}
.nav {
  display: flex;
  gap: 20px;
}
.nav-link {
  color: #c0c8d4;
  text-decoration: none;
  font-size: 14px;
}
.nav-link.router-link-active {
  color: #409eff;
  font-weight: 600;
}
.nav-sep {
  color: #5a6a7d;
}
.app-main {
  max-width: 1280px;
  width: 100%;
  margin: 0 auto;
  padding: 20px 24px 48px;
}
</style>
