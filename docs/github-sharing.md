# 将当前版本分享给组员

## Fork 和 branch 的区别

**Fork 是你或小组名下的一份 GitHub 仓库；branch 是同一仓库内的一条开发线。**
若主要目的是分享基于原版 TinyLEO 的扩展，建议 fork 原版仓库，然后把现有开发分支
推到该 fork。无需重新下载源码、重新做改动或删除 Git 历史。
如果你本来就是原仓库维护者，也可以按小组约定直接在那里推送开发分支。

## 本项目的分享位置

- 小组仓库：[Scaled_TinyLeo_DND_Demo](https://github.com/Leoqwq/Scaled_TinyLeo_DND_Demo)
- 扩展分支：[`codex/canada-topology-validator`](https://github.com/Leoqwq/Scaled_TinyLeo_DND_Demo/tree/codex/canada-topology-validator)
- 原版仓库：[TinyLEO-toolkit/TinyLEO](https://github.com/TinyLEO-toolkit/TinyLEO)

本地 `origin` 用于你的小组仓库，`upstream` 保留原版仓库。
小组仓库的 `main` 包含已合并的 Canada / Live / Replay 扩展，组员可以直接浏览仓库首页。
上面的开发分支保留用于追溯开发历史。

## 组员下载

```sh
git clone --branch main https://github.com/Leoqwq/Scaled_TinyLeo_DND_Demo.git
cd Scaled_TinyLeo_DND_Demo
```

然后阅读 [组员导览](team-guide.md)。不需要重新 fork 才能浏览或下载。

## 后续更新

后续功能从小组 `main` 建立新的开发分支，提交并推送后，在小组仓库内发 PR 合并回
`main`。创建 PR 时核对目标仓库为 `Leoqwq/Scaled_TinyLeo_DND_Demo`，避免误选原版仓库。
未提交修改不会随 push 上传；提交前使用 `git diff` 和 `git diff --cached` 核对内容。

## 演示附件

生成的 HTML、匹配录制及校验和可以单独共享；源码仓库保留构建工具与复现说明。
请在实际上传附件后补充下载链接。当前仓库没有附带完整真实实验录制，
不要将合成测试 fixture 作为实验结果分享。

保留原版 LICENSE、作者与论文引用。新增忽略规则不会从既有 Git 历史移除文件；
若发现已提交的真实凭据，应先撤销凭据，再单独处理历史。

参考：[GitHub 官方 fork 远端配置说明](https://docs.github.com/en/pull-requests/how-tos/work-with-forks/configuring-a-remote-repository-for-a-fork)。
