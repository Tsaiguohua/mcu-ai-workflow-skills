---
name: project-workbench-builder
description: 搭建或规范 MCU/嵌入式项目工作台，包括标准目录、项目记忆文件、源码分层、资料位置和归档规则。适用于新建 MCU 项目、整理混乱项目文件、补充 AI 可读取的项目记忆，或给老项目补建可维护结构时。
---

# 项目工作台搭建

目标是让人和 AI 都知道资料在哪里、项目到哪一步、哪些事实已确认。不要为了“规范”制造额外文档负担。

## 原则

- 不创建没人维护的文档。
- 优先保留四类高价值信息：项目状态、接口速查、芯片资料摘录、调试记录。
- 贴合团队现有工具，不强迫迁移编辑器或 IDE。
- 老项目不要上来大搬家，先补索引和项目记忆。

## 推荐结构

```text
project/
  docs/
    datasheets/
    app-notes/
    extracts/
  hardware/
    schematics/
    interface-map.md
    dangerous-outputs.md
  requirements/
    product-behavior.md
    changes.md
  firmware/
    source/
    architecture.md
    build-notes.md
  debug/
    debug-log.md
    test-plan.md
  memory/
    project-status.md
    decisions.md
```

如果现有仓库已有约定，优先适配现有结构。

## 固件分层建议

在适合当前项目时使用：

- `driver`：只表达 MCU 外设机制，不表达产品含义。
- `bsp`：表达板级语义、引脚映射、有效电平、安全默认态。
- `component`：parser、CRC、环形缓冲、滤波、通用算法等可复用组件，不反向依赖产品 app。
- `app`：产品功能模块。
- `app_workflow`：多个 app 模块之间的业务编排。
- `main`：初始化、tick 消费、周期任务调度，不承载业务策略。

## 工作流

1. 先检查现有文件、构建脚本和目录习惯。
2. 提出最小必要结构。
3. 只创建有实际用途的目录和记忆文件。
4. 写简洁用途说明。
5. 整理混乱文件时，先分类，再移动低风险资料；源码大迁移必须谨慎。
6. 记录原始位置和关键假设。

## 起始文件模板

`memory/project-status.md`:

```markdown
# 项目状态
- 当前阶段:
- 当前阻塞:
- 下一步:
- MCU/板卡:
- 工具链:
- 已确认事实:
- 待确认问题:
```

`memory/decisions.md`:

```markdown
# 决策记录
| 日期 | 决策 | 原因 | 影响范围 | 可回退方式 |
|---|---|---|---|---|
```

## 常见坑

- 设计七八个文档，原理图一改就要全部同步，工程师自然不用。
- 把 AI 工作流变成额外填表。
- 让项目上下文只留在聊天记录里。
- 没弄清构建路径就强行重排老项目目录。

