# START HERE｜从这里开始

欢迎使用 Workspace OS 2.0 的 Obsidian 知识库。

## 先记住一条规则

Obsidian 保存的是“思考和索引”，Workspace 保存的是“真实文件”。

- 笔记、待办、会议结论、项目决策：写在这个知识库。
- 视频原片、代码、合同、安装包：继续放在 `D:\Workspace` 对应的项目目录。
- 在项目笔记里写清楚真实文件路径，不要把大型文件搬进知识库。

## 每天最简单的用法

1. 临时想法先写到 `00_Inbox（收件箱）`。
2. 点击左侧日历按钮，打开今天的每日笔记。
3. 每个项目在 `02_Projects（项目笔记）` 建一张项目主页。
4. 可长期复用的经验放到 `03_Knowledge（知识沉淀）`。
5. 每周清理收件箱，把完成的内容移动到 `99_Archive（归档）`。

## 建一个项目笔记

1. 在 `02_Projects` 新建笔记，名称与真实项目文件夹一致。
2. 按 `Ctrl+P`，输入“插入模板”，选择 `Project-Home`。
3. 在“项目路径”填写真实目录，例如：
   `D:\Workspace\01_Projects\Work\Active\Xiaomi_项目名`
4. 以后把需求、进度、决策、版本和会议链接都写在这张主页。

## 工作与生活示例

- 工作代码：真实文件放在 `01_Projects/Work/Active/项目名`；Obsidian 只建同名项目主页。
- 生活视频：原片与成品放在 `01_Projects/Personal/Active/视频项目名`；Obsidian 记录选题、脚本、剪辑清单和发布链接。

## 当前同步规则

Windows 日常打开：
`D:\Workspace\02_Knowledge\ObsidianVault`

NAS 保存副本：
`W:\02_Knowledge\ObsidianVault`

目前不是自动同步。请优先编辑电脑本地副本，重要修改完成后把整个
`ObsidianVault` 复制到 NAS。不要同时编辑两边。Mac 的本地知识库与自动同步会在
Mac 安装阶段单独配置。

## 让 Codex 自动写工作日志

- 默认自动：Codex 在 Workspace OS 项目中完成安装、配置、功能改动、自动化或故障修复后，会写入当天的 Daily Note。
- 强制记录：说“记录到 Obsidian”“写入知识库”“更新工作日志”，或输入 `$obsidian-worklog`。
- 本次跳过：说“这次不要记录”。
- 日志位置：`01_Daily/YYYY-MM-DD.md`。
