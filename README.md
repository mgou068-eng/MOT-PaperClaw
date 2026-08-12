<p align="center">
  <strong>MOT-PaperClaw</strong>
</p>

# MOT-PaperClaw

### 多目标跟踪论文自动追踪与分析流水线

arXiv -> 单篇深读 Issue -> 每日汇总 -> GitHub Pages 阅读页

MOT-PaperClaw 从 [RS-PaperClaw](https://github.com/thinson/RS-PaperClaw) 改造而来，已将论文发现、语义筛选、分析提示、标签体系、日报和前端全部切换为多目标跟踪领域。

## 2026 顶会顶刊每日精选

定时工作流每天北京时间 09:30 刷新候选池，并从尚未解读的论文中选择 1 篇进行 10 问深度分析。目标 venue 包括 CVPR、ICCV、ECCV、NeurIPS（NIPS）、ICMR、ICML、AAAI、TPAMI、TIP、IJCV、TCSVT、Pattern Recognition 和 ACM MM。

候选必须满足：2026 年正式 venue 元数据、明确的 MOT 研究信号，以及可供全文处理的 arXiv ID 或来源核验的公开 PDF。候选队列持久化在 `papers/top_venue_queue_2026.json`；尚未公布论文列表或没有公开全文的 venue 不会用未核验预印本补位。

手动运行：

```bash
cd skills/mot-paper-pipeline
python3 scripts/cli.py top-venue
```

## 范围

收录：

- 2D/3D MOT、行人/车辆/航拍/细胞跟踪
- 多摄像头与多视角跟踪
- 在线/离线、tracking-by-detection、端到端 MOT
- 直接服务于 MOT 的数据关联、ReID、运动建模、轨迹推理和遮挡恢复

排除：纯单目标跟踪、普通目标检测、无 MOT 实验的纯 ReID、SLAM、姿态估计和只预测未来轨迹的论文。

## 核心能力

| 模块 | 行为 |
|---|---|
| 候选发现 | 使用 MOT 专用 arXiv 查询词与强证据 regex |
| 语义复筛 | LLM 判断是否真正维持多实体身份与轨迹 |
| 单篇报告 | TL;DR、中文摘要、MOT 受控标签、首页预览、10 问深度分析 |
| 实验解读 | 区分 HOTA、IDF1、MOTA/AMOTA，关注数据集、协议、速度与消融 |
| 日报与归档 | GitHub Issue + `daily_reports/YYYYMM/YYYYMMDD.md` |
| 通知 | 可选飞书/钉钉推送 |

## 目录

```text
MOT-PaperClaw/
|-- .github/workflows/           # 定时与手动流程
|-- daily_reports/               # MOT 日报归档
|-- docs/                        # GitHub Pages 阅读页
|-- papers/issue_index.json      # arXiv ID -> Issue 索引
`-- skills/mot-paper-pipeline/   # 核心脚本、配置、提示词和测试
```

## 快速开始

```bash
cd skills/mot-paper-pipeline
./bootstrap.sh
```

编辑生成的 `.env`，至少设置：

```dotenv
GITHUB_TOKEN=github_pat_xxx
LLM_API_KEY=xxx
MOT_GITHUB_REPO=your-github-user/MOT-PaperClaw
```

运行环境检查与 dry-run：

```bash
python3 scripts/cli.py doctor
python3 scripts/cli.py filter --dry-run --date 20260730
```

运行完整流程：

```bash
python3 scripts/cli.py run --no-notify
```

## 配置

筛选词与 regex 在 `scripts/config/filter_keywords.json`，LLM 复筛边界在 `scripts/prompts/filter_cross_prompt.md`。受控标签与深度分析维度位于同目录的 `tags_prompt.md` 和 `summarize_prompt.md`。

GitHub Actions 需要：

- Secret: `MOT_GITHUB_TOKEN`、`LLM_API_KEY`
- Variable: `MOT_GITHUB_REPO`、`LLM_MODEL`、`LLM_API_URL`
- 可选：`DINGTALK_WEBHOOK`、`FEISHU_TARGET`

`RS_*` 环境变量仅作为旧部署的兼容别名，新部署请使用 `MOT_*`。

## 测试

```bash
cd skills/mot-paper-pipeline
python3 -m unittest discover -s tests -v
```

## License

MIT，见 `skills/mot-paper-pipeline/LICENSE`。
