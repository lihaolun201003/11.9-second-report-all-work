# experiments 索引

本目录为 2026-10-30 之后的 1024 通道三维光波导实验数据（此前的 Structured/Spatial/Hybrid 等历史方案不在本仓库）。

| 目录 | 内容 | 关键结果 |
|---|---|---|
| [auto_u_bundle_hybrid](auto_u_bundle_hybrid/README.md) | Hybrid 基线上自动 U 分组 + 自动层分配 | 12,960（与 Hybrid 持平） |
| [z1_multilayer_150um](z1_multilayer_150um/README.md) | 150 µm 层栈 5/7/9/11 层 Z1 实验 | 7L：11,984；5L 基线：13,920 |
| [z1_edge_optimization](z1_edge_optimization/experiment_report.md) | 7L Z1 边缘/邻边交叉专项 | 11,984 → **6,078**；Z1 10,976→5,256 |
| [z1_topology_global_7L](z1_topology_global_7L/experiment_report.md) | 7L 全局层分配 + 邻边拓扑 A/B/C/D | 四组均未优于 6,078（诚实负结果） |
| [code_z1](code_z1/) | 新增实验代码：层栈、溯源、重布、多层验证器 | — |

所有实验均保持 1024 条连接、端口、R=15、净空 0.08、写速 1 mm/s；验证状态 exploratory_only（层高未确认）。
