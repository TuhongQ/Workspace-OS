# 文件命名规范

推荐：`项目或主题_内容_YYYY-MM-DD_v版本_状态.扩展名`，例如：

- `BOE_DataWrite_TestReport_2026-07-22_v0.3_DRAFT.docx`
- `BOE_DataWrite_Demo_2026-07-22_v1.0_RELEASE.mp4`
- `iPhone_DecryptTool_2026-07-22_v1.2_RELEASE.zip`
- `AI_FileClassifier_Prompt_2026-07-22_v0.4.md`

状态只用 `DRAFT`、`REVIEW`、`APPROVED`、`RELEASE`、`ARCHIVE`。日期用于外部交付、审核快照、每日素材、合同/会议和同版本多次输出；持续更新且完全由 Git 管理的源码文件通常不带日期。

文档版本表达内容修订，通常用 v0.1/v1.0；软件版本表达兼容性和发布承诺，使用 SemVer；两者不可混用。视频审核版用 `v001_REVIEW` 递增，批准后另存 `v1.0_RELEASE`，原始审核版保留。

禁止使用“最终、最终版、最新版、新的、新版、修改版、副本、copy、new、final-final”。这些词无法排序，也无法证明批准状态。

