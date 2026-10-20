# HKU Agent

本分支集成 Qodex/Pi Agent 与 exam-checker 服务。

## 目录结构

```text
.
├── docs/                         # 各功能的设计文档
└── pi-coding-agent/              # Pi 源码及其配套服务
    ├── packages/                 # Pi monorepo packages
    ├── services/
    │   └── exam-checker/         # 试题解析、审校与题库服务
    ├── start-exam-checker-db.sh  # 启动 PostgreSQL 并执行迁移
    ├── start-exam-checker.sh     # 启动 exam-checker API
    └── pi-test.sh                # 从源码启动 Pi
```

## 启动数据库

```bash
cd pi-coding-agent
./start-exam-checker-db.sh
```

数据库配置和表结构说明见
[`pi-coding-agent/services/exam-checker/DATABASE.zh-CN.md`](pi-coding-agent/services/exam-checker/DATABASE.zh-CN.md)。

## 启动 exam-checker

首次使用时，在 `pi-coding-agent/.env` 中配置本地数据库连接和模型 API。真实密钥不得提交到 Git。

```bash
cd pi-coding-agent
./start-exam-checker.sh
```

## 启动 Pi

```bash
cd pi-coding-agent
npm install
./pi-test.sh
```

Pi 通过 HTTP 调用 `services/exam-checker`，服务地址可通过 `EXAM_CHECKER_SERVICE_URL` 配置。
