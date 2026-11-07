# 前端 — AI 低代码平台

基于 **Vite + React 18 + TypeScript** 的单页应用，内置手工实现的 **shadcn/ui 风格**组件库，支持 **i18n（中/英，默认英文）** 与 **system / light / dark** 主题。

English: [README.md](README.md) · [项目根 README](../README.md)

## 运行

```bash
cp .env.example .env        # 可选；默认把 /api 和 /mcp 代理到 :8000
pnpm install
pnpm dev                    # http://localhost:5173
pnpm typecheck && pnpm build
```

Vite 开发服务器把 `/api` 和 `/mcp` 代理到 `http://127.0.0.1:8000`。执行 `pnpm build` 之后，FastAPI 后端也会在 `/` 直接托管 `dist/`（通过 `scripts/start.sh` 实现单端口模式）。

## 页面（HashRouter）

| 路由 | 页面 | 亮点 |
| --- | --- | --- |
| `/login` | 登录 | 演示账号、SSO 按钮、MFA 质询、OTP 绑定、Passkey 登录 |
| `/sso/callback` | SSO 回调 | 消费真实 SSO 重定向带回的 token |
| `/` | 总览 | 实时统计、活动图表、快捷操作、近期运行与审计动态 |
| `/forms` | 表单设计器 | 字段面板、拖拽排序画布、属性编辑器、实时预览、提交记录 |
| `/workflows` | 流程编排 | 可拖拽 DAG 画布、贝塞尔连线、连接模式、节点配置、校验/运行、实例日志 |
| `/knowledge` | 知识库 | 集合、文档、分块、BM25 检索测试与上下文拼装、多格式拖拽上传（Office/PDF/Markdown 等）含解析状态与即时索引 |
| `/agents` | AI 智能体 | 带工具调用步骤与来源引用的对话、智能体配置（知识库/技能/MCP 服务/工作流搜索式绑定）、运行时信息、工具目录 |
| `/mcp` | MCP 服务 | 独立服务注册表、传输/认证配置、探测/同步工具发现、启用/禁用、按服务调用、平台工具目录，以及调用日记看板（统计/图表/筛选/CSV 导出）与 REST 工具调用 |
| `/skills` | 技能 | 可安装目录、安装/启用/禁用/卸载/重装、可编辑文件管理器（查看/新建/更新/删除/重载）、可选关联 MCP 服务、同步 |
| `/models` | AI 模型服务 | 六类模型（llm/asr/tts/embedding/rerank/vision）、配置 CRUD、每类默认项、密钥只写脱敏、连通性测试、运行时元数据 |
| `/rbac` | 用户与角色 | 用户/角色 CRUD、重置密码、角色×权限矩阵 |
| `/auth` | 认证配置 | SSO Provider 配置、全局/按角色/按用户 MFA 策略 |
| `/audit` | 审计日志 | 可筛选日志表格 + JSON 详情查看 |
| `/settings` | 设置 | 语言、主题、个人资料、密码、OTP 二维码绑定、Passkey 管理、平台设置 |

深链接：`/#/forms?form=leave_request`、`/#/workflows?workflow=leave_approval`、`/#/agents?agent=general_copilot`。

## 目录结构

```
src/
  main.tsx                 providers: HashRouter · Theme · I18n · Toast · AppContext
  App.tsx                  路由 + 鉴权守卫 + 启动闪屏
  index.css                shadcn HSL 设计变量、动态背景、工具类
  components/ui/           basic.tsx (Button/Input/Card/Badge/Select/Switch/Segmented…)
                           overlay.tsx (Dialog/Confirm/Tabs/Toast/Dropdown)
                           table.tsx
  components/layout/       AppShell.tsx (侧边栏、顶栏、主题/语言切换、用户菜单)
  components/              PageHeader.tsx, Charts.tsx (SVG 图表、统计卡片、环形图)
  i18n/                    locales.ts (每种语言 740 个叶子键), index.tsx (provider + t())
  theme/ThemeProvider.tsx  system/light/dark，监听 prefers-color-scheme
  store/AppContext.tsx     session、/meta/bootstrap 目录、can(permission)
  lib/                     api.ts (fetch 客户端 + 401 处理), utils.ts, webauthn.ts
  pages/                   14 个页面模块
  types.ts                 共享 TypeScript 模型
```

## 设计系统

- 遵循 shadcn/ui 约定：HSL CSS 变量（`--background`、`--primary`、`--border` 等）、`radius`、`cn()` = `clsx` + `tailwind-merge`、`cva` 变体、lucide-react 图标。
- 浅色动态渐变背景叠加细网格；暗色主题复用同一套变量。全程不使用 emoji，所有图标均为 SVG。
- 移动优先：侧边栏变为抽屉，网格收拢为单列，工具栏自动换行。

## i18n 与主题

- `I18nProvider` 默认 **英文**，把选择持久化到 `localStorage`，同步设置 `<html lang>`，键缺失时回退英文。
- `ThemeProvider` 默认 **system**，监听 `prefers-color-scheme`，切换 `dark` 类并更新 `meta[theme-color]`。
- 两者都可以在顶栏和设置页切换；服务端默认值来自 `/api/v1/settings`。

## 数据流

`lib/api.ts` 封装 `fetch`，统一处理 JWT Bearer Token、JSON 序列化、`ApiError` 以及全局 `401 → 登出` 事件。`AppContext` 在登录后一次性加载 `/auth/me` 与 `/meta/bootstrap`；各页面从 context 读取目录数据（字段类型、节点类型、权限、Provider、Agent 运行时），而不是硬编码。

## 许可证

[MIT](../LICENSE)
