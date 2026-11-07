# 嵌入式 AI Skills 复现包

这是一套嵌入式 AI 工作流复现版，根据我自己的方法论、踩坑和 Codex skill 结构重建出的可落地版本。

## 包含的 Skill

- `embedded-workflow-orchestrator`: 总控工作流，把资料、接口、需求、代码、验证和维护串起来。
- 升级为“嵌入式 AI 项目经理”
- 增加项目状态判断：新项目、老项目加功能、排错、移植、bring-up 等
- 增加资料完整度检查
- 增加 skill 自动调度规则
- 增加常见组合流程
- 增加项目记忆回写要求
- `mcu-datasheet-extractor`: 芯片手册提取。
- `schematic-interface-analyzer`: 原理图/网表接口分析。
- 增强硬件坑扫描
- 增加 P0-P3 风险分级
- 增加有效电平、上电默认态、BOOT/SWD/JTAG、I2C/SPI/UART/USB/SDIO/FSMC、电源等风险检查
- 增加复用冲突表
- 增加和现有代码宏定义联动检查
- `product-requirement-organizer`: 产品需求整理。
- `project-workbench-builder`: 项目工作台搭建。
- `firmware-dev-executor`: 固件开发、编译、修复执行。
- `source-maintenance-reader`: 老项目源码理解与维护。
- `embedded-project-learning-retrospective`: 根据源码和验证证据做阶段复盘，给后续工作留下未决项和下一步。

## 使用方式

把需要的 skill 目录完整复制到 Codex 的 skills 目录后使用，保留目录内的模板等资源。建议先在真实项目副本中验证，不要直接对生产项目做大规模自动修改。

总入口按本轮意图区分只读、方案和实施。下面是三种典型用法：

- 「帮我读一下这个旧工程的串口接收路径，先别改代码。」先核对实际构建目标和生效的源码，给出证据和待验证项。
- 「给旧工程补个项目索引，记录实际构建目标和资料位置，目录别动。」工作台优先复用项目现有文档，也可使用其[索引](project-workbench-builder/assets/project-index.md)和[状态](project-workbench-builder/assets/project-status.md)模板。
- 「接着上次查串口丢帧，先看项目状态和调试记录。」先对照当前源码、构建目标和上次证据，再从未完成的验证继续。需要阶段性总结时，使用项目学习复盘。

源码检查、构建、主机测试、烧录与板端验证分别记录；旧日志不能证明本轮结果。本批没有引入自动烧录或数据采集工具。

## 核心思想

- AI 做初稿，工程师做判断。
- 对话不是资产，项目记忆才是资产。
- 先标准化，再复制。
- 不追求一步全自动，先把半自动流程跑通。
- 关键风险必须人工确认和硬件验证。

