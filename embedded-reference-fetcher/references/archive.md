# 公开参考资料归档

需要 Python 3.9+，无第三方库。先由人或技能确认官方发布页和版本，再提供直接文件 URL。参数只用于一次明确获准的下载；脚本不会搜索、自动装包、解压或运行文件。

```text
python3 embedded-reference-fetcher/scripts/reference_fetch.py --url https://raw.githubusercontent.com/torvalds/linux/v6.12/Documentation/kbuild/modules.rst --allowed-host raw.githubusercontent.com --kind kernel-doc --product "Linux kernel" --version v6.12 --format text --record linux-kbuild-v6-12 --filename modules.rst --out-dir docs/references
```

Windows 可以把 `python3` 换成 `python`。上例是版本化文档，不代表项目应选择该内核版本。

- 仅接收无凭据、无查询参数和片段的公开 HTTPS 链接；跳转目标也必须在明确允许的主机中。只有核对该发布方使用了另一个官方分发主机时才添加 `--allowed-host`。站点需要登录、签名链接或交互时交回用户或经批准的专用获取方式。
- 支持 `pdf`、`zip`、`text`（UTF-8）。限制响应大小及超时，拒绝常见错误页和不匹配的格式；这是下载检查，不替代阅读 PDF、确认 ZIP 内容或检查许可证。已知官方 SHA-256 时提供 `--sha256`；否则只记录本次下载的指纹。
- 每次成功写入独立归档目录，保存原文件与 `source.json`，不会覆盖已有记录。以 `source.json` 为成功归档标记；没有该文件的目录不能用作已完成记录。
- `source.json` 保存用户传入的资料身份、初始 URL、实际 URL、重定向链、时间、大小和 SHA-256。型号、版本和适用范围仍应以官方页面和原文为准。
- 标准输出为 JSON；失败返回非零。用 `--help` 查看种类、大小及超时选项。
