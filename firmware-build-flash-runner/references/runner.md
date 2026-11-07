# 运行器使用说明

需要 Python 3.9 或更高版本。参数中的路径相对于当前工作目录。为每次操作创建独立运行目录；报告和日志默认保留在你指定的 `--out-dir` 下。

| 命令 | 用途 | 依赖 |
| --- | --- | --- |
| `probe` | 查找工具，不打开设备 | 无额外依赖 |
| `targets` | 列出单个 Keil 工程的目标和输出配置 | 无额外依赖 |
| `build-keil` | 以明确目标重建，保存本次日志和产物 | Windows、Keil µVision、工程所需编译器和设备包 |
| `build-cmake` | 构建已配置的目录和指定目标 | CMake 及项目所需工具链 |
| `capture` | 在明确窗口内只接收 UART 字节 | pySerial、已确认的本机串口 |
| `replay` | 回放分块的原始输入，生成同格式的证据 | 无额外依赖 |
| `flash-plan` | 对 STM32 裸二进制生成烧录预览 | 无额外依赖，不调用烧录工具 |

```text
python firmware-build-flash-runner/scripts/board_runner.py probe
python firmware-build-flash-runner/scripts/board_runner.py targets --project App.uvprojx
python firmware-build-flash-runner/scripts/board_runner.py build-keil --project App.uvprojx --target "Board A" --artifact Objects/App.axf --board board-a --out-dir debug/runs
python firmware-build-flash-runner/scripts/board_runner.py build-cmake --build-dir build --target app --artifact build/app.bin --board board-a --out-dir debug/runs
python firmware-build-flash-runner/scripts/board_runner.py capture --port COM3 --baud 115200 --board board-a --seconds 5 --out-dir debug/runs
python firmware-build-flash-runner/scripts/board_runner.py replay --input examples/uart-fragmentation/input.jsonl --out-dir debug/runs
```

- 路径和目标只是示例。未加入 PATH 的可信可执行文件通过 `--tool` 指定。Keil 产物需匹配该目标配置中的输出目录和名称；第一版仅支持工程目录内的 Keil 输出。CMake 使用已配置的目录，多配置生成器需指定 `--config`。
- 构建可能运行项目自己的构建钩子。先核对并确认项目和命令。在同一输出目录避免并发构建。Keil 需要本轮日志的可识别汇总、允许的返回码和零错误；CMake 需要成功返回码。二者都需要新生成或重写且非空的指定产物。CMake 增量构建没有重写产物时，报告未能证明本轮产物，可使用新配置的构建目录重试。
- 串口以 8N1、无流控接收，不发送数据。脚本在打开前将 DTR/RTS 设为非活动，但驱动仍可能产生瞬态；对复位线敏感的设备，先确认连接与影响。可提供 `--build-report` 关联声明的固件哈希；脚本不能读回并证明板上实际固件。
- `flash-plan` 要求带 `--board` 的成功构建报告、归档的 `.bin`、`--probe-serial`、`--address`、`--partition-start`、`--partition-end` 与 `--out-dir`。区间为左闭右开；只校验**写入字节**在声明区间内，不能证明扇区擦除不会涉及相邻数据。预览不会连接设备，执行前另行核对芯片、分区、扇区及授权。

## 结果与证据

读取标准输出 JSON 和 `report.json`；失败返回非零。构建成功归档 `artifact.*` 和 SHA-256，原始工具输出留在 `process.log` 或 `keil.log`。不要把手工改名或旧产物当作本轮构建。

采集和回放输出 `capture.bin` 与 `chunks.jsonl`，报告分别记录它们的 SHA-256。每条包含接收块序号、从主机开始计时的毫秒数、字节偏移、长度和原始十六进制数据；回放输入只需要 `elapsed_ms`、`data_hex`，例如 `{"elapsed_ms":12,"data_hex":"1011"}`。主机读块不能推出物理线上或 MCU 回调的边界。无数据、断连、超出预算或超时保留可用的部分证据；读取报告状态后才能使用这些数据。回放和串口接收都不等于功能通过。

工具参数依据：[Keil µVision 命令行](https://www.keil.com/support/man/docs/uv4/uv4_commandline.asp)、[STM32CubeProgrammer 用户手册](https://www.st.com/resource/en/user_manual/dm00403500-stm32cubeprogrammer-software-description-stmicroelectronics.pdf)、[pySerial API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html)。
