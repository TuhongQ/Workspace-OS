# 安全与隐私

## 链接与 Windows reparse point

Workspace OS 不会把 `Path.is_symlink()` 当作唯一链接判断。Windows junction、mount point
等 reparse point 也会通过文件属性识别：

- 安全审计发现指向 Workspace 外部的链接时产生 `LINK_ESCAPES_WORKSPACE` ERROR。
- 搜索、JSON 索引、重复检测、关系图、NEXUS 文件扫描、变化哨兵和 Inbox 不跟随链接。
- 跨设备清单把 reparse point 标记为未验证并阻止交接包导出。
- 快照发现 junction、不可可靠重建的 reparse point 或越界符号链接时，以
  `UNSAFE_REPARSE_POINT` 中止，清理 partial，且不更新恢复点状态。
- 产品发行包、恢复工具包和通用 release 构建在预览阶段检查整个选定源边界；发现
  junction、符号链接或其他 reparse point 时分别以 `UNSAFE_EXPORT_SOURCE_LINK` 或
  `UNSAFE_RELEASE_SOURCE_LINK` 拒绝导出。打包完成前还会重新计算源内容指纹，源发生
  并发变化时以 `SOURCE_CHANGED_DURING_EXPORT` 中止并清理 partial。
- 版本识别、旧文件迁移和项目模板渲染统一使用不跟随链接的遍历器，外部目录中的文件
  不会被选为正式版本、写入迁移清单或参与模板内容替换。

这样可以避免外部目录内容被误索引、误打包、误移动或混入快照。

遵循最小权限、默认拒绝、数据最少化。Private、合同、账户、证书与密钥分别设置访问控制；不把密码、Token、SSH Key 或证书私钥写入配置、日志、索引或 Git。

AI 隐私模式：metadata-only（默认，只允许名称/扩展名/大小等）、local-only（内容只给本地模型）、content-preview（明确授权的小片段）、full-content（逐次显式授权）。外部 Provider 必须独立实现并记录目的、数据范围与保留政策。

扩展 `AIClassifierProvider` 时只实现 `classify(metadata, text_preview=None)`：OpenAI Provider 从环境变量读取凭据并通过结构化输出返回 category/confidence/reason；Ollama Provider 只访问 `localhost` 并用于 local-only；其他兼容 API 使用同一返回协议。Provider 不得自行打开文件，内容预览必须由 CLI 在用户选择的隐私模式下显式传入；默认实例不配置任何外部 Provider。

脚本只用参数数组和 Path API，不拼接 shell 命令；所有路径解析后校验；失败不修改源数据或留下半成品。

告警通知默认只处理 ERROR/CRITICAL，并在生成发件箱时移除本地路径与凭据。可选 webhook
地址只能通过 `WORKSPACEOS_ALERT_WEBHOOK_URL` 环境变量注入，不应写入配置文件、脚本、
Obsidian 或日志。模板见 `config/notifications.example.json`。

变化哨兵采用 `metadata-only`，不读取内容。报告样本只保存在本机
`08_Indexes/Security`；NEXUS 只嵌入状态和计数，不嵌入样本路径。全文搜索排除整个
`08_Indexes`，避免安全、恢复、健康和告警报告中的路径被再次索引。

安全暴露审计只读取受支持的小型文本文件，并在内存中匹配高置信度凭据模式。报告
永远不保存命中值，只保存规则编号、相对路径和行号；受保护目录内容默认跳过。详见
`docs/security-audit.md`。
