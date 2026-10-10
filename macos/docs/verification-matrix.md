# Workspace OS 2.0 验证矩阵

目标级完成度与外部环境缺口见 [completion-audit.md](completion-audit.md)。

这份矩阵用于交接和回归测试。所有“通过”均应有命令输出或报告文件作为证据；不能在没有外部条件时把异机备份、磁盘加密或 macOS shell 检查标记为通过。

## 核心质量门

| 能力 | 验证命令/入口 | 证据 | 当前结果 |
|---|---|---|---|
| Python 单元测试 | `python -m unittest tests.test_workspace_os -q` | 测试输出 | 92 项通过 |
| Python 编译 | `python scripts/python/release_verify.py --package <包>` | 内存编译结果 | 通过且不生成 `__pycache__` |
| Windows 脚本解析 | PowerShell `[scriptblock]::Create(...)` | 47 个 `.ps1` | 通过 |
| 标准便携包 | `python scripts/python/portable_package.py --verify <包>` | `PORTABLE-MANIFEST.json` | 1,098 个文件通过 |
| 发布前总检查 | `python scripts/python/release_verify.py --package <包> --latest-pointer <LATEST.json> --output <报告>` | JSON 汇总 | 单元测试、编译、PowerShell 解析、包清单、隐私/敏感路径、完成度审计文档、关键文件和最新指针一次检查；报告输出为显式可选 |
| 包内 CLI | 包内 `runtime/python/python.exe workspace_cli.py --version` | `Workspace OS 2.0.0` | 通过 |

## 数据可靠性

| 能力 | 验证入口 | 当前结果 |
|---|---|---|
| 快照 | `snapshot --apply` | 文件清单、源一致性和校验报告生成 |
| 快照校验 | `verify-snapshot` | 清单与库存哈希一致 |
| 恢复 | `restore --apply` | 恢复到新目录，`post_verified=true` |
| 恢复演练 | `restore-drill` | 抽样恢复通过，临时内容清理 |
| 恢复工具包 | `recovery-kit --apply` + `recovery-kit-verify` | 归档校验通过 |

## 搜索、安全与运维

- 搜索维护报告状态为 `healthy`，内容哈希漂移为 0。
- 安全内容审计未发现敏感凭据或越界链接。
- `change-guard` 能识别新增文件；证据链 `evidence-verify --verify-current` 通过。
- `operations-drill` 能检测 SLO 预算耗尽、连续失败和篡改，并阻断篡改后的追加。
- 计划任务审计在实际机器上下文下 9/9 通过；使用测试路径时出现参数不一致属于预期告警。
- `recovery-readiness --drill-report <隔离报告> --recovery-kit-report <隔离报告>` 支持在不覆盖工作区历史报告的情况下绑定当前快照演练和恢复工具包证据。
- 恢复就绪度证据区分 `restic_scope=workspace-bundled`、`restic_command_available` 和已初始化/已检查仓库，避免把携带二进制误判为异机备份。

## 跨设备

- Windows 与 MacBook 设备清单比较：18 个文件相同、0 冲突、0 未验证。
- 设备回执状态为 `verified`，离线交接包校验通过，simulation 模式无覆盖/删除。
- Windows 控制中心优先读取 `Get-SmbMapping` 的 OK 状态 Workspace UNC 映射；映射盘失效时自动回退，且保留手动 NAS 设置入口。

## 尚需真实环境完成的项目

1. 配置独立物理介质上的加密异机备份（Restic 或等价方案），才能满足 3-2-1。
2. 在实际 MacBook 上执行 `bash -n scripts/macos/*.sh` 和启动烟测。
3. 在管理员权限下复核真实 Workspace 受保护目录 ACL 与卷加密证据。
