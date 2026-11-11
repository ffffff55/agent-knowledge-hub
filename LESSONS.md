# Lessons from merged work

本仓库的代码由 agent 编写、审查、合并和发布。每次清理 loop 跑完，都要把当天的 commit 过一遍，只记三类事：

- 修完又返工的
- 本来不该合的
- 验证做得太糙的

读这个文件，再改代码。每条教训先写一句规则，再写原因和证据。`Seen` 统计的是有复盘抓到它的不同日期。同一条在 3 个不同日子出现，就挪进 [docs/code-standards.md](docs/code-standards.md)，并在下面的「已转正」里留一条指向。

## 条目格式

**一句话规则。**
- 哪个 commit / issue 出的事，后果是什么。
- 修复它的 commit。
- Done right: 做对的例子（如果有）。
- Seen N× (YYYY-MM-DD, YYYY-MM-DD).

## 当前教训

（还没有。第一次清理 loop 跑完后，从这里开始追加。）

## 已转正

（Seen 满 3 个不同日后，把原文挪到 code-standards，并在这里留一行索引。）
