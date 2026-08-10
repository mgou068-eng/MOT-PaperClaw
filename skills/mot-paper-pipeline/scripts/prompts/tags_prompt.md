# MOT 标签提取 Prompt

你是多目标跟踪研究员。请从标题和摘要中提取 3-6 个英文标签。

规则：
1. 第一个标签必须是 `Multi-Object Tracking`。
2. 其余优先从以下受控词表选择：`2D MOT`, `3D MOT`, `Multi-Camera`, `Online Tracking`, `Offline Tracking`, `End-to-End`, `Tracking-by-Detection`, `Data Association`, `Re-Identification`, `Motion Modeling`, `Trajectory Reasoning`, `Occlusion`, `Open-Vocabulary`, `Pedestrian Tracking`, `Vehicle Tracking`, `Aerial Tracking`, `Cell Tracking`, `Benchmark`。
3. 只选择论文明确涉及的标签，不要推测。
4. 用英文逗号分隔，只返回标签列表。

标题：{title}

摘要：{abstract}
