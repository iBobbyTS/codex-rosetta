---
name: analyze-huge-jsonl
description: Freeze and stream-split huge JSONL logs (including 100+ GB) into hourly append-only files without loading the source into memory. Use when analyzing oversized JSONL/gateway logs, especially when repeated full-file reads could exhaust memory or interfere with a live writer.
---

# Analyze Huge JSONL

当前只实现第一阶段：冻结源文件并按小时拆分。二次按时间范围提取、临时分析目录和清理流程暂不实现，不能自行扩展范围。

## Safety contract

- 先在同一目录把源文件重命名为带 UTC 时间的 `.frozen-...jsonl`。重命名不会停止已经打开的文件描述符；用 `lsof` 检查 frozen 路径，并连续观察 `size/mtime` 确认没有写入。若仍有 writer，停止并要求用户轮换/停止 logger；不要猜测文件已经稳定。
- 禁止 `cat`、无界 `jq`、`read_text()` 或把 JSONL 全部读入内存。只运行 bundled script；每次 `split` 调用最多读取 2 GiB（`--max-read-bytes 2147483648`），使用断点继续，不会重复扫描已完成偏移。
- 源文件、split 输出和 checkpoint 都保留；不要删除或覆盖源数据。生产网关不主动重启或杀进程。
- 原始 JSONL 字节逐行保留。无法解析或没有 timestamp 的行分别写入 `invalid.jsonl` / `undated.jsonl`，不得丢弃。

## Workflow

1. 检查文件大小、inode、mtime 和 writer；将源文件 `mv` 为 frozen 名称。
2. 创建源文件旁的 `split/` 目录。
3. 反复运行下面命令，直到输出 JSON 中 `complete` 为 `true`。每次调用都从 `.split-state.json` 的 offset 继续：

   ```bash
   python /Users/ibobby/.codex/skills/analyze-huge-jsonl/scripts/split_jsonl.py split \
     --source /path/log.frozen-20260806T223600Z.jsonl \
     --split-dir /path/split --max-read-bytes 2147483648
   ```

   可以用外层循环自动重复调用，但不要在循环外再运行任何会全量读取源文件的命令。脚本每轮打印累计 `bytes`、`records` 和按小时的字节统计，可直接换算 GiB（除以 `1024**3`）。
4. 后续轮换产生的新 frozen 文件若落入已存在的小时，脚本以 append 模式写入同名小时文件，绝不 truncate/覆盖；每个 inode 都有独立 checkpoint。
5. 报告每小时统计时说明：小时按 UTC 文件名划分；`invalid.jsonl` 与 `undated.jsonl` 单独统计；若中途被杀，最后一次未保存 checkpoint 的尾部可能需要从 checkpoint 偏移重跑，必须核对记录数后再分析。
6. 拆分完成后运行不重读原始内容的快速校验：

   ```bash
   python /Users/ibobby/.codex/skills/analyze-huge-jsonl/scripts/split_jsonl.py validate \
     --source /path/log.frozen-20260806T223600Z.jsonl --split-dir /path/split
   ```

   `ok=true` 需要同时满足：checkpoint complete、源 inode offset 到达 EOF、所有 split 的 checkpoint 字节数之和等于源文件大小、每个输出文件的实际大小匹配 checkpoint，并且每个小时文件的首尾抽样 timestamp 与文件名小时一致。该校验不会证明每一行都被重新解析；若需要逐行内容审计，必须另行设计有界分批扫描。

## Script

`scripts/split_jsonl.py` 仅使用 Python 标准库，按小块读取并保留有限大小的单条记录，支持顶层或点路径 timestamp（默认 `timestamp`）。它不会做二次拆分或时间范围提取；这是有意保留的后续阶段边界。
