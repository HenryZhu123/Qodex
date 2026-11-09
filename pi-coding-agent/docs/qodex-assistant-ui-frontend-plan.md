# Qodex × assistant-ui 前端适配计划

## 1. 结论

Qodex 不需要从零实现 assistant-ui runtime。优先采用官方 `@assistant-ui/react-pi` 的 `usePiRuntime` 和 UI primitives，在 Qodex 侧实现一个符合 `PiClient` 契约的适配层，把现有服务映射给前端：

- `SessionDirectory` / `SessionManagement`：会话列表、创建、切换、删除；
- `Transcript`：历史消息、流式文本、reasoning、工具调用和运行状态；
- `AgentController`：发送、取消、steer、follow-up、resume、compact；
- `Models`：模型列表、当前模型、thinking level；
- Qodex `Client` + Chord services：继续承担路由、订阅、取消和状态同步。

不建议正式版直接使用 `@assistant-ui/react-pi/node` 的 `createPiNodeClient()`。它会在 Web 服务进程内另建一套 Pi session supervisor，绕过 Qodex 已有的 server/session/Chord 架构，容易形成两套会话生命周期。它只适合作为 1～2 天的 UI 可行性验证。

## 2. 目标与非目标

### MVP 目标

用户可以在浏览器中：

1. 查看、新建、切换和删除 Qodex 会话；
2. 发送消息并实时看到文本、reasoning 和工具调用结果；
3. 在运行中发送 follow-up 或 steer，并查看待处理队列；
4. 取消当前运行，断线后恢复到权威快照；
5. 选择模型和 thinking level；
6. 查看连接、运行、重试、压缩和错误状态；
7. 使用 Markdown、代码块、复制按钮和图片输入。

### MVP 非目标

- 不在浏览器保存模型密钥；密钥继续由 Qodex 服务端读取；
- 不让浏览器直接访问本地 Unix socket；
- 不在第一版实现会话分叉树、插件管理、终端模拟器、完整设置中心；
- 不引入 Assistant Cloud，Qodex 继续作为会话数据的唯一事实来源；
- 不让前端执行模型工具；工具仍由 Qodex agent/server 执行。

## 3. 推荐架构

```text
Browser
  assistant-ui Thread / ThreadList / Composer
  @assistant-ui/react-pi usePiRuntime
                 │ PiClient（JSON-safe）
                 │ HTTP commands + SSE snapshots/events
                 ▼
Qodex Web Gateway（Node，长驻进程）
  QodexPiClientAdapter
  SessionProjection / TranscriptProjection
                 │ @earendil-works/pi-client
                 │ Chord typed services over framed CBOR
                 ▼
Qodex Server
  SessionDirectory / SessionManagement
  Transcript / AgentController / Models
                 ▼
AgentHarness + tools + model providers
```

边界原则：

- assistant-ui 只负责展示和交互状态；
- `usePiRuntime` 负责把标准 thread/composer/tool UI 行为映射到 `PiClient`；
- Gateway 负责浏览器可用的 HTTP/SSE、鉴权和 Qodex 服务投影；
- Qodex 服务端快照始终是权威状态，SSE 断线不等于取消 agent run；
- 前端刷新后先拉快照，再订阅增量；不依赖浏览器缓存重建运行状态。

## 4. 技术选型

### Web 应用

- React + TypeScript；
- Next.js App Router，使用 Node runtime，不部署到 serverless/edge；
- `@assistant-ui/react`、`@assistant-ui/react-pi`；
- assistant-ui 的 shadcn registry 组件；
- Tailwind CSS；
- Vitest + Testing Library；
- Playwright 用于端到端测试。

选择 Next.js 的原因是可以在一个应用内承载页面、HTTP command routes 和 SSE gateway，并与 assistant-ui 官方 Pi 示例保持接近。若后续需要独立部署，再把 Gateway 拆成 Fastify 服务，浏览器侧 `PiClient` 契约不变。

依赖必须固定精确版本。开始实现前先做 Qodex `0.85.1` 与当前 `@assistant-ui/react-pi` 的兼容性 spike；其 peer range 虽然覆盖 `>=0.80.8`，但正式开发不能只依赖 peer range 判断兼容。

### 仓库布局

```text
pi-coding-agent/
  apps/qodex-web/
    app/
      api/qodex/...
      page.tsx
    components/
      assistant-ui/
      qodex/
    lib/
      qodex-client/
      projections/
    test/
```

把 `apps/*` 加入 npm workspaces，但保持 Web 构建与现有 package 发布流程分离；根级 `check` 应覆盖类型、格式和 browser boundary 检查。

## 5. 数据契约映射

| assistant-ui / PiClient 能力 | Qodex 来源 | 适配规则 |
|---|---|---|
| thread list | `SessionDirectory.state.sessions` | `sessionId` 作为 `remoteId`；`createdAt` 放 metadata |
| create thread | `SessionManagement.create()` + `attach()` | 创建后等待 attachment hydration 完成再返回快照 |
| open thread | `attach()` + `Transcript.state.snapshot` | 切换时先停止旧订阅，再绑定新 attachment generation |
| delete thread | `SessionManagement.remove()` | 删除当前会话时清空选中态并返回幂等结果 |
| messages | `LaneSnapshot.transcript` | 用 entry `id/parentId/timestamp` 保留稳定标识和树关系 |
| streaming assistant | `operation.streamingMessage` | 与已落盘 assistant entry 去重；快照覆盖增量态 |
| reasoning | assistant content 中的 thinking/reasoning part | 映射为 assistant-ui reasoning part，默认折叠 |
| tool calls | assistant `toolCall` + `runningTools` + tool result entry | 以 `toolCallId` 合并 planned/running/settled 状态 |
| send | `AgentController.prompt()` | idle 时发送；只在 `accepted: true` 后进入 running |
| cancel | `requestAbort(operationId)` | operationId 必须来自当前 snapshot，避免取消错误 run |
| follow-up | `AgentController.followUp()` | running 时普通 Enter 入 follow-up queue |
| steer | `AgentController.steer()` | Cmd/Ctrl+Shift+Enter 或显式模式进入 steer queue |
| queued items | `snapshot.queues` | 映射到 composer queue；第一版只支持整体清理或服务端已有能力 |
| model | `Models.state` + `Models.select()` | 模型切换成功后以 replicated state 回写为准 |
| thinking | `Models.getThinkingLevels()` / `selectThinking()` | 只显示当前模型支持的级别 |
| retry/compaction/error | `operation.retry`、`lastResult`、`faulted` | 显示非消息型状态条，不伪造成 assistant 文本 |

### Transcript 投影规则

1. `message/user` → user message；文本与图片拆成标准 content parts。
2. `message/assistant` → assistant message；text、reasoning、tool call 保留顺序。
3. `message/toolResult` 不单独显示为普通气泡，合并到相同 `toolCallId` 的 tool part。
4. `compaction` → timeline system event；默认简洁显示，可展开摘要和 token 信息。
5. `branch_summary` → timeline system event；MVP 只读。
6. `custom` → 未注册类型使用安全 fallback，不直接渲染任意 HTML。
7. `operation.streamingMessage` 是临时消息；对应 durable entry 到达后必须替换，不能重复追加。
8. 任意重连快照都可完整重建 UI，不要求重放全部历史事件。

## 6. Gateway API

保持与官方 `createPiHttpClient()` 接近，便于最大化复用：

```text
GET    /api/qodex/threads
POST   /api/qodex/threads
GET    /api/qodex/threads/:id
DELETE /api/qodex/threads/:id
POST   /api/qodex/threads/:id/messages
POST   /api/qodex/threads/:id/cancel
POST   /api/qodex/threads/:id/queue/clear
GET    /api/qodex/models
POST   /api/qodex/threads/:id/model
POST   /api/qodex/threads/:id/thinking
GET    /api/qodex/threads/:id/events
```

如果官方 `PiClient` 的既有方法能完整承载 Qodex 语义，直接实现该接口，不另造浏览器协议。只有 `compact`、导航、插件命令等 Qodex 专有能力放入扩展接口，并通过独立 hooks 暴露，不污染基础 chat runtime。

SSE 约束：

- 建连首先发送完整 snapshot，之后发送有序更新；
- 每条事件带 `threadId`、单调递增 revision 和 schema version；
- 浏览器断开只释放订阅，不调用 `requestAbort`；
- 重连从新 snapshot 恢复，MVP 不做 durable event replay；
- Gateway 对同一 thread 复用 Qodex subscription，避免每个浏览器连接重复订阅底层服务；
- 慢消费者超过缓冲上限时断开并要求重拉 snapshot，不能无限积压内存。

## 7. 页面与交互

### 桌面布局

```text
┌───────────────┬──────────────────────────────────┬────────────────────┐
│ 会话列表       │ 当前会话                         │ 运行信息 / 设置      │
│ 新建、搜索     │ 消息、reasoning、tool cards      │ 模型、thinking       │
│ 最近会话       │ 队列                             │ context、重试、压缩   │
│               │ composer                         │ 连接状态              │
└───────────────┴──────────────────────────────────┴────────────────────┘
```

移动端使用单列：会话列表和运行信息变成 drawer。

### MVP 组件

- `QodexShell`：三栏布局与移动端 drawer；
- `QodexThreadList`：会话加载、空态、创建、删除；
- `QodexThread`：基于 assistant-ui Thread primitives；
- `QodexComposer`：发送、停止、图片、follow-up/steer 提示、queue；
- `QodexToolFallback`：工具名、参数、运行中、结果、错误；
- 常用工具 renderer：read、write/edit、bash 优先；
- `ModelPicker` / `ThinkingPicker`；
- `RunStatusBar`：连接、retry、compaction、fault；
- `HostUiDialogHost`：后续承载 confirm/select/input/editor。

### 交互语义

- idle + Enter：新 prompt；
- running + Enter：follow-up；
- running + Cmd/Ctrl+Shift+Enter：steer；
- Stop：只取消当前 snapshot 中的 operationId；
- 切换会话不自动取消原会话运行；
- 工具运行结果默认折叠，错误默认展开；
- reasoning 默认折叠，用户可展开；
- 模型不可用或凭证缺失时 composer 可输入但不可发送，并显示服务端给出的修复提示。

## 8. 分阶段实施

### Phase 0：兼容性验证（1～2 天）

- 建最小 Next.js 页面；
- 使用官方 `createPiNodeClient()` + `usePiRuntime` 跑通一个临时 workspace；
- 验证 assistant-ui 版本、React 版本、Markdown、tool UI、queue 和取消；
- 记录 Qodex `0.85.1` 与 adapter 的类型/运行时差异；
- 此阶段代码可丢弃，不接入正式会话目录。

退出条件：浏览器能完成一次包含工具调用的完整对话，并能取消与刷新恢复。

当前实现状态（2026-11-03）：`apps/qodex-web` 已完成最小页面、官方 Pi runtime 接入、SSE、session 列表/恢复、Markdown/Reasoning/Tool fallback、queue 与 cancel 路由。默认模型已修正为 `talkweb/deepseek-flash`，浏览器实测完成流式文本、reasoning、`read` 工具调用及结果展示；类型检查和生产构建通过。

### Phase 1：QodexPiClientAdapter（3～5 天）

- 建立 Gateway 到现有 Qodex server 的连接；
- 绑定 `SessionDirectory`、`SessionManagement`、`Transcript`、`AgentController`、`Models`；
- 实现 snapshot projection 与命令映射；
- 实现 SSE 共享订阅、revision、重连与错误规范；
- 用 fake service source 做 adapter 单元测试。

退出条件：不使用 `createPiNodeClient()`，仍能完成 Phase 0 的全部用例。

### Phase 2：MVP UI（3～5 天）

- 接入 Thread、ThreadList、Composer；
- 完成三栏响应式布局；
- 完成 model/thinking、状态条、queue 和通用 tool fallback；
- 增加 read/write/edit/bash 的定制 renderer；
- 增加空态、loading、断线和错误态。

退出条件：主要功能不需要终端辅助即可使用。

### Phase 3：可靠性与安全（2～4 天）

- Gateway 鉴权、origin 校验、输入大小限制、速率限制；
- workspace allowlist，禁止由浏览器提交任意宿主路径；
- SSE 慢消费者和资源释放测试；
- 多 tab、切换会话、断网重连、服务重启测试；
- CSP、Markdown URL sanitization、禁止任意 HTML；
- 日志关联 `requestId/threadId/operationId`，不记录密钥和完整敏感 prompt。

退出条件：所有 P0/P1 验收场景通过，并完成威胁检查。

### Phase 4：增强能力（按优先级迭代）

- extension host UI：confirm/select/input/editor；
- slash command palette 与 skills；
- compact、分叉/导航树；
- workspace picker（仅服务端 allowlist）；
- 会话命名、搜索、归档；
- 文件/差异预览和更丰富的工具卡片；
- Radius 远程连接与多 server 切换。

## 9. 测试计划

### 单元测试

- 每种 `Entry` 和 assistant content part 的投影；
- streaming message 被 durable entry 替换且不重复；
- tool call/result 乱序、并行工具和错误结果合并；
- operationId 变化时旧 cancel 不会取消新 run；
- session attachment generation 切换时旧更新被忽略；
- model/thinking replicated state 回写。

### 集成测试

- session create → attach → hydrate → send → stream → settle；
- running 时 follow-up 和 steer；
- SSE 断开、重连、快照恢复；
- 切换会话时两个运行互不干扰；
- Qodex server 不可用、版本不匹配、模型未配置；
- 删除当前和非当前会话。

### E2E 测试

- 首次打开和空会话；
- 包含 read/bash/edit 的完整 turn；
- 取消运行；
- 刷新页面后恢复同一会话；
- 移动端布局；
- 键盘发送、steer、焦点和基本无障碍。

## 10. 验收标准

MVP 完成需同时满足：

1. 首 token 延迟相对现有 Qodex 后端额外增加不超过 150 ms（同机环境）；
2. 10,000 条 transcript 可以分页/虚拟化，不冻结主线程；
3. 刷新或短暂断网不会取消正在运行的 agent；
4. 同一 tool call 在 UI 中只有一个稳定卡片，流式更新不闪烁；
5. 旧 session/operation 的迟到事件不会污染当前会话；
6. 前端 bundle 不包含 provider key、Node-only Pi 模块或本地路径机密；
7. Web UI 与 TUI 同时连接时，双方最终看到一致的权威 transcript；
8. 核心流程具备单元、集成和 E2E 覆盖，类型检查与格式检查通过。

## 11. 主要风险与处理

| 风险 | 影响 | 处理 |
|---|---|---|
| 官方 `react-pi` 与 Qodex fork 语义漂移 | adapter 编译通过但运行异常 | 锁版本；Phase 0 建契约测试；Qodex adapter 隔离版本差异 |
| Gateway 与 Qodex server 形成双重会话所有权 | 重复 run、状态不一致 | Gateway 只做 presentation；session/agent 状态只由 Qodex server 持有 |
| snapshot 与增量竞态 | 消息重复或回退 | revision + attachment generation；snapshot 权威覆盖 |
| 浏览器断线误取消任务 | 长任务丢失 | SSE unsubscribe 与 agent abort 严格分离 |
| assistant-ui 默认能力超过后端能力 | 出现无效编辑/分支按钮 | 只声明已实现 capability；未实现 handler 不暴露 |
| 工具输出过大 | UI 卡顿、SSE 堵塞 | 服务端截断/分页，UI 折叠与虚拟化 |
| Web 暴露本机代码执行能力 | 高安全风险 | 鉴权、workspace allowlist、Node 长驻内网部署、明确风险提示；后续再加沙箱/审批 |

## 12. 第一批开发任务

1. `WEB-001`：建立 `apps/qodex-web` 和依赖边界检查。
2. `WEB-002`：官方 Pi adapter 兼容性 spike。
3. `WEB-003`：定义并冻结 `QodexPiClientAdapter` 契约测试夹具。
4. `WEB-004`：SessionDirectory/Management 映射。
5. `WEB-005`：Transcript snapshot/event 投影。
6. `WEB-006`：AgentController send/cancel/queue 映射。
7. `WEB-007`：Models 映射。
8. `WEB-008`：HTTP/SSE Gateway 与重连。
9. `WEB-009`：assistant-ui shell、thread list、thread、composer。
10. `WEB-010`：工具卡片与运行状态。
11. `WEB-011`：安全与资源限制。
12. `WEB-012`：集成/E2E、文档和本地启动脚本。

## 13. 参考

- assistant-ui 官方 Pi adapter：<https://github.com/assistant-ui/assistant-ui/tree/main/packages/react-pi>
- assistant-ui 安装：<https://www.assistant-ui.com/docs/installation>
- assistant-ui custom runtime 选择：<https://www.assistant-ui.com/docs/runtimes/custom/overview>
- assistant-ui thread 模型：<https://www.assistant-ui.com/docs/runtimes/concepts/threads>
- assistant-ui tool UI：<https://www.assistant-ui.com/docs/tools/tool-ui>

