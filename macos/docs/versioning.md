# 版本管理

源码使用 Git 和语义化版本 `v主版本.次版本.修订号`：不兼容变更升主版本，向后兼容功能升次版本，修复升修订号。文档用 v0.1、v0.2、v1.0、v1.1；视频审核用 v001、v002，批准后生成 v1.0_RELEASE。

正式发布目录必须含 `README.md`、`CHANGELOG.md`、文件本体、`SHA256SUMS.txt`、`release-manifest.json`。清单 Schema 位于 `search/release-manifest.schema.json`，核心字段为 schema_version、release_version、generated_at 和 files；每个文件记录相对路径、字节数、SHA-256 和 UTC 修改时间。

最新版本判断依次考虑 RELEASE/APPROVED、版本号、日期、release 目录、修改时间。临时、缓存、代理文件永不作为正式最新版本。

