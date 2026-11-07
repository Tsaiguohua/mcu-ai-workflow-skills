# 嵌入式 AI Skills 复现包

一套面向 MCU 和 RTOS 工程的 Codex 技能。覆盖从资料整理、工程理解和固件开发，到用日志、回放和实验逐步排查问题。

## 包含的 Skill

当前收录 12 个技能，可按任务单独使用。

| 技能 | 用途 |
| --- | --- |
| [embedded-workflow-orchestrator](embedded-workflow-orchestrator/SKILL.md) | 判断任务范围，选择技能，跨会话交接 |
| [project-workbench-builder](project-workbench-builder/SKILL.md) | 整理工程索引、构建目标、资料和进度 |
| [mcu-datasheet-extractor](mcu-datasheet-extractor/SKILL.md) | 提取手册中的引脚、时序、电气参数及出处 |
| [schematic-interface-analyzer](schematic-interface-analyzer/SKILL.md) | 核对原理图、引脚复用、电源、上电状态和危险输出 |
| [product-requirement-organizer](product-requirement-organizer/SKILL.md) | 整理产品行为、边界和验收条件 |
| [source-maintenance-reader](source-maintenance-reader/SKILL.md) | 确认当前构建目标、读旧源码和追踪调用链 |
| [firmware-dev-executor](firmware-dev-executor/SKILL.md) | 在授权范围内实现、构建和回归 |
| [embedded-project-learning-retrospective](embedded-project-learning-retrospective/SKILL.md) | 复盘证据和未决项，让下轮接着做 |
| [embedded-debug-loop](embedded-debug-loop/SKILL.md) | 排序候选原因，设计可区分假设的实验 |
| [embedded-telemetry-planner](embedded-telemetry-planner/SKILL.md) | 规划观测信号、采样、时间基准和判据 |
| [firmware-build-flash-runner](firmware-build-flash-runner/SKILL.md) | Keil/CMake 构建、串口接收、离线回放及烧录预览 |
| [firmware-quality-reviewer](firmware-quality-reviewer/SKILL.md) | 只读检查固件改动、触发条件和验证缺口 |

## 使用方式

把需要的 skill 目录完整复制到 Codex 的 skills 目录后使用，保留目录内的模板等资源。建议先在真实项目副本中验证，不要直接对生产项目做大规模自动修改。

总入口按本轮意图区分只读、方案和实施。典型用法：

- 「帮我读一下这个旧工程的串口接收路径，先别改代码。」先核对实际构建目标和生效的源码，给出证据和待验证项。
- 「给旧工程补个项目索引，记录实际构建目标和资料位置，目录别动。」工作台优先复用项目现有文档，也可使用其[索引](project-workbench-builder/assets/project-index.md)和[状态](project-workbench-builder/assets/project-status.md)模板。
- 「接着上次查串口丢帧，先看项目状态和调试记录。」先对照当前源码、构建目标和上次证据，再从未完成的验证继续。需要阶段性总结时，使用项目学习复盘。
- 「我已经有串口抓包，帮我区分是接收漏字节还是拼帧出错。」先核对抓包来自哪个目标和固件，再设计能区分两种原因的实验。只在用户授权时执行对应操作。

## 第二批：构建、调试与证据

运行器需要 Python 3.9+。用 `probe` 检查本机工具，不打开设备。Keil 需要 Windows 上的 µVision 和项目工具链；CMake 需要已配置的构建目录；物理串口接收另需 pySerial。详细命令与证据格式见[运行器说明](firmware-build-flash-runner/references/runner.md)。

源码检查、构建、主机测试、串口收取、烧录与板端验证分别记录。每次构建使用独立日志并归档本轮产物和 SHA-256；旧日志或没变化的产物不能证明本轮成功。串口只接收原始字节，不发送命令；打开串口可能影响某些设备的复位线。

烧录目前只生成 STM32CubeProgrammer 预览：检查归档的 `.bin` 和声明的写入区间，**不会连接板卡或执行烧录**。没有实板验证时不要将构建或回放写成板端通过。

当前验证范围：CMake/GCC 主机样例和离线回放已跑通；Keil 构建参数、成功和失败判定经模拟测试，本机两份工程副本的实际 Keil 调用均无日志超时，尚未验证成功构建。串口断连和烧录预览经过离线测试，尚未在实板上验证。

### 无板卡复现实例

从仓库根目录运行以下命令。样例需 CMake、Ninja 和可用的主机 C 编译器：

```text
python firmware-build-flash-runner/scripts/board_runner.py probe
python examples/uart-fragmentation/run_demo.py --out-dir demo-runs
python -B -m unittest discover -s tests -v
```

样例将一帧以 `2+2` 字节离线回放，分别构建并运行修复前后的 C 解析器：旧版漏报，修复版输出完整帧，整帧和短尾部输入也要通过。运行目录保留原始字节、构建报告、产物哈希和回归结果。测试还检查错误目标、构建失败、旧产物、超时、断连和越界烧录计划；模拟结果不表示真实硬件已经验证。

## 核心思想

- AI 做初稿，工程师做判断。
- 对话不是资产，项目记忆才是资产。
- 先标准化，再复制。
- 不追求一步全自动，先把半自动流程跑通。
- 关键风险必须人工确认和硬件验证。

