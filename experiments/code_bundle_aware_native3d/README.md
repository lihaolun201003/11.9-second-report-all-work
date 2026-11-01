# Bundle-aware Native 3D Routing 代码（研究原型）

本目录收录"自动线束分组 + 线束级三维规划 + Native 3D 搜索原型"的可复现代码。
工程主体仍在本地 `OpticalWaveguideRouter2D/four_side_1024/`（复用冻结的
fslw / l3d / d56 / v3c4 几何与验证器），本目录只新增 bundle3d 研究模块与 campaign 脚本。

## 模块（`four_side_1024/bundle3d/`）

| 文件 | 作用 |
|---|---|
| `features.py` | 每条连接的几何/拓扑特征（起终点、方向、类别、连接器、U 嵌套区间、走廊坐标等） |
| `orbits.py` | 以 C4 旋转四元组为规划原子；构造四元组特征与空间 bbox |
| `compatibility.py` | 四元组兼容性图（邻近、方向、共享走廊、次序兼容、端口邻近、交叉代价、同层重合风险） |
| `clustering.py` | 4 种自动分组：图聚类 A、跨类别图聚类 A2、走廊约束 B、同类固定基线 C；并计算内部交叉率/兼容度等指标 |
| `corridors.py` | 线束冲突图、整束层分配（贪心图着色）、走廊 bbox 计划 |
| `bundle_lift.py` | 线束级 3D 抬升：bundle-first 顺序 + 目标层偏好，复用冻结 lift 引擎与验证/修复循环 |
| `reroute.py` | 线束级 Rip-up & Reroute 基础（候选四元组、blocker 组识别、联合重布、载荷构建） |
| `validate_local.py` | 冻结 2D 审计 + 严格 C4 审计封装 |
| `native_search.py` | Native 3D A* 原型：状态 (x,y,heading,layer)，直线/R15 圆弧/垂直 S 换层动作，3D 障碍云方向感知净空，端点冻结模板对接 |
| `visualize.py` | 分组/走廊/兼容热力图/统计/代表连接等图件 |

## Campaign 脚本（`outputs/manual_c4_new_connectivity/BUNDLE_AWARE_NATIVE_3D/`）

| 文件 | 作用 |
|---|---|
| `run_p0.py` | 输入快照 + 自动分组 + 图件（P0） |
| `run_p1.py` | 线束级走廊/层规划；2D 顺序消融 + 3D 分层消融（P1） |
| `p2_ripup_search.py` / `p2_candidate_window.py` / `p2_region_replan.py` / `p2_same_bundle.py` | 三种线束级拆线重布（P2） |
| `run_p3.py` | Native 3D A* 原型测试（P3） |
| `make_bwn3d_report.py` | 生成技术报告 |
| `finalize2.py` | （继承自上一战役）层扫汇总/对比/图件 |

## 运行顺序

```bash
python outputs/manual_c4_new_connectivity/BUNDLE_AWARE_NATIVE_3D/run_p0.py
python outputs/manual_c4_new_connectivity/BUNDLE_AWARE_NATIVE_3D/run_p1.py --stage=2d
python outputs/manual_c4_new_connectivity/BUNDLE_AWARE_NATIVE_3D/run_p1.py --stage=3d
python outputs/manual_c4_new_connectivity/BUNDLE_AWARE_NATIVE_3D/p2_candidate_window.py
python outputs/manual_c4_new_connectivity/BUNDLE_AWARE_NATIVE_3D/run_p3.py
python outputs/manual_c4_new_connectivity/BUNDLE_AWARE_NATIVE_3D/make_bwn3d_report.py
```

## 说明

- 不覆盖旧实验 `NEW_MANUAL_CSV_1024_FULL_CAMPAIGN`；新结果全部在
  `BUNDLE_AWARE_NATIVE_3D/`。
- P3 是原型：完整冻结 3D 验证器集成尚未完成，报告中明确区分 Native 3D 与
  2D+lift 的贡献；最终 1024 布局仍来自 2.5D 管线。
- 层数 >5 时需要同步扩展 `lift_cross.LAYER_IDS`、`l3d.layers.ROUTING_LAYER_IDS`、
  `l3d.validate_l3d*.ROUTING_LAYER_IDS`（脚本已处理）。
