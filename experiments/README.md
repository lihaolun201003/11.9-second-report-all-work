# experiments 索引
本目录为 2026-10-30 之后的 1024 通道三维光波导实验数据（此前的 Structured/Spatial/Hybrid 等历史方案不在本仓库）。
| 目录 | 内容 | 关键结果 |
|---|---|---|
| [auto_u_bundle_hybrid](auto_u_bundle_hybrid/README.md) | Hybrid 基线上自动 U 分组 + 自动层分配 | 12,960（与 Hybrid 持平） |
| [z1_multilayer_150um](z1_multilayer_150um/README.md) | 150 µm 层栈 5/7/9/11 层 Z1 实验 | 7L：11,984；5L 基线：13,920 |
| [z1_edge_optimization](z1_edge_optimization/experiment_report.md) | 7L Z1 边缘/邻边交叉专项 | 11,984 → **6,078**；Z1 10,976→5,256 |
| [z1_topology_global_7L](z1_topology_global_7L/experiment_report.md) | 7L 全局层分配 + 邻边拓扑 A/B/C/D | 四组均未优于 6,078（诚实负结果） |
| [code_z1](code_z1/) | 新增实验代码：层栈、溯源、重布、多层验证器 | — |
| [MANUAL_GROUP_15L_COMPARISON](MANUAL_GROUP_15L_COMPARISON/README.md) | 人工分组 L1–L4 + 旧算法 L5–L15 的完整 1024 通道对照（150 µm 层距）+ 逐层布线图 | 992/1024；74,626 vs 基线 75,794（−1,168，−1.54%）；人工仅 16/192 条抬升可落地（如实记录） |
| [code_manual_group_15l](code_manual_group_15l/) | 人工分组对照与逐层出图代码 | — |
| [MANUAL_GROUP_15L_COMPARISON_FIXED](MANUAL_GROUP_15L_COMPARISON_FIXED/README.md) | 修复版人工 U 型：按真实端点重新生成深度/嵌套 R15 U（非旧 2D 局部抬升）+ 人工阶段验证 | L1 64/64、L2 0/64、L3 0/64、L4 2/64（66/256）；L2–L4 被冻结 z1/z2 平面封死，未进入 1024（如实记录） |
| [code_manual_group_15l_fix](code_manual_group_15l_fix/) | 修复版人工 U 几何与验证代码（manual_u_geometry + 重写 compare_15L） | — |
| [MANUAL_FIRST_1024_FULL](MANUAL_FIRST_1024_FULL/report.md) | 人工优先全流程：256 条人工 U 固定 + 768 条重布 + L5-L15 抬升 + 冻结验证 | 992/1024；85,416 交叉（vs 75,794，+12.69%）；共同集合 968 条 +4,746；100 clearance 违规（如实记录未完全合法） |
| [code_manual_first_full](code_manual_first_full/) | 人工优先 2D 重布/3D 抬升/统计代码 | — |
所有实验均保持 1024 条连接、端口、R=15、净空 0.08、写速 1 mm/s；验证状态 exploratory_only（层高未确认）。
