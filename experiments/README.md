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
| [MANUAL_LAYERS_20L](MANUAL_LAYERS_20L/report.md) | L1–L20 确定性人工分层：完整分配审计 + 固定层三维构建器（执行中） | 分配 1024/1024（L6=128、L7=128、L8–L19 按组、Z2 接口 68、L20 未用）；Z2 固定层 304/444 已通过三维检查后运行被环境终止，未得完整结果 |
| [code_manual_layers_20l](code_manual_layers_20l/) | 20 层分配/固定层三维构造/统计图代码 | — |
| [manual_20l_fixed_assignment](manual_20l_fixed_assignment/README.md) | 最终 L1–L20 人工指定分层全流程：256 人工 U→L2–L5、Z1 相对边→L7/L8、Z2→L9–L20；checkpoint + 完整验证 + 21 层出图 + 报告 | **673/1024；Z1 511/512、Z2 162/512；0 几何违规；4357 唯一交叉对（共同集口径已注明）**；Z2 接口 0/68，瓶颈为 z=0.5 端口共轨与 Z1 过渡冲突（如实记录） |
| [u_depth_transition_joint_opt](u_depth_transition_joint_opt/README.md) | 不改变 256 条人工 U 端点/配对/目标层，仅优化 U 深度与两端 S 升降位置；A 固定深度 / B 允许加深 + L7/L8 集成 | baseline 复现 **12/48**；A **20/48（+8，0 违规）**；B 允许加深但 **0 条加深、20/48 与 A 同**（深度假设负结果）；集成 L7/L8 137/255、Z2 16/48、0 违规 |
| [bidirectional_1mm_1024_full](bidirectional_1mm_1024_full/README.md) | 1 mm 玻璃内 Z1 向下 / Z2 向上双向 10 物理层全 1024 通道实验；严格 R15、0.08 mm 3D 净空、真实负 z；含 Phase 1–6、逐层统计、12 张图、完整验证 | **735/1024**；Z1 **430/512**、Z2 **305/512**、人工 U **256/256**；Z2 接口 **48/48**；Z1×Z2 交叉 **0**；**0 几何违规**；实际最小净空 0.0878648 mm；共同 548 条交叉 2197→4201（未降低，如实记录） |
| [bidirectional_1mm_target_first_1024](bidirectional_1mm_target_first_1024/README.md) | 第二轮：首先分配 12 个独立 Z2 目标物理层（A/B，50 μm 间距）+ 目标层 R15 联合重布；12 层验证不合法后，在合法 4 层栈上完成 C | A **644**（330916 违规）、B **726**（388276 违规）证明 12 独立层当前非法；C **801/1024**（Z1 447、Z2 354、U 256/256、接口 48/48、**0 违规**、最小净空 0.0878648 mm）；恢复 66 条、0 丢失；共同集合交叉未降低（如实记录） |
| [bidirectional_1mm_50um_corrected_full](bidirectional_1mm_50um_corrected_full/README.md) | 纠正“全局 80 μm 净空”错误前提：确认 1 mm 玻璃、50 μm 最小层距、双向；修复在线 world 与最终 validator 一致性；18 主体层（6 Z1 + 12 独立 Z2）从空 world 重建并做 R15 目标层恢复 | 旧 A/B 旧规则 330916/388276 → 新 50 μm 规则 9957/11777（旧层栈仍不合格）；新 B **723/1024（0 违规）**；新 C **809/1024**：Z1 416、Z2 393、U 256/256、接口 48/48、**0 违规**、最小净空 **0.052673907 mm**；旧 735/801 保留 |
所有实验均保持 1024 条连接、端口、R=15、写速 1 mm/s；净空阈值按实验模式区分（旧实验 0.08，本轮 correction 50 μm 模式为 0.05）；验证状态 exploratory_only（层高未确认）。

## Native 3D 系列（多高度主体 + 中途换层，2026-11-03 ~ 11-04）

| 目录 | 内容 | 关键结果 |
|---|---|---|
| [native_3d_crossing_opt_1024](native_3d_crossing_opt_1024/README.md) | Phase 1（A/B/C）：允许光波导主体中途换层；精确 R15 双圆弧 S 曲线；跨圆弧区间整体重构；独立 Validator | A 单线换层 2606→2601；B 批量 2606→2559；C 全局 2606→**2440**（−6.37%）；1024/1024、118 段换层、0 违规；独立 Validator PASS |
| [native_3d_joint_opt_1024](native_3d_joint_opt_1024/README.md) | Phase 2（D/E/F）：多线路联合让路（D）、圆弧区域整体重构（E）、全局联合优化（F）+ 近失候选区间微调 | 最终 2440→**2409**（−31，−1.27%）；1024/1024、138 段换层、0 违规；独立 Validator PASS；D/E 被人工 U 冻结与真实三维净空限制（0 直接收益） |

## 近零交叉优化系列（1024 通道，2026-11-02 ~ 11-04）

| 目录 | 内容 | 关键结果 |
|---|---|---|
| [non_c4_crossing_opt_1024](non_c4_crossing_opt_1024/README.md) | 解除非人工线路 C4 旋转对称层绑定 + 基于交叉冲突图和模拟退火的层分配（E5 基线） | 1024/1024；11890 → **2606** 同层交叉；368 条人工 U 冻结；严格 0.05 mm 三维净空；0 违规 |
| [native_3d_crossing_opt_1024](native_3d_crossing_opt_1024/README.md) | Phase 1（A/B/C）：主体中途换层（精确 R15 双圆弧 S 曲线）、跨圆弧区域重构、独立三维验证 | A 单线 −5；B 批量 −47；C 全局 2606→**2440**（−6.37%）；1024/1024、118 段换层、0 违规；独立 Validator PASS |
| [native_3d_joint_opt_1024](native_3d_joint_opt_1024/README.md) | Phase 2（D/E/F）：多线路联合让路、圆弧区域整体重构、全局联合优化 + 近失候选区间微调 | 2440→**2409**（−31）；1024/1024、138 段换层、0 违规；独立 Validator PASS；D/E 被人工 U 冻结与真实三维净空限制（诚实负结果记录） |