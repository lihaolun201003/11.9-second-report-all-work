# SPEC — Phase 2 数据/接口/验收规范

## 数据模型（与 Phase-1 完全兼容）
* 路线：`parts` = 交替的 `flat{z_mm, layer_id, primitives:[line|arc], tag}` 与 `transition{start,direction,z0,z1,radius_mm,footprint_mm,theta_rad,end,length_mm,tag}`；
  一条主体可包含多个不同高度的 flat 段（多高度主体）。
* 21 个物理高度（真实 z，非 layer_id 单调）：-0.35,-0.30,-0.25,-0.20,-0.15,-0.10,-0.05,0.00,0.05,0.10,0.15,0.20,0.25,0.30,0.35,0.40,0.45,0.50,0.55,0.60,0.65 mm。
* 换层几何：精确 R15 双圆弧 S 曲线，水平足迹 `2R·sin(acos(1−|dz|/2R))`；跨圆弧区域时两端 S 曲线必须落在相邻直线段上，中间弧段在目标高度原样保留。
## 文件
* `routes_l3d.json`：1024 条路径（route_id/source/target/parts/长度/元数据）
* `crossing_stats.json`：按真实物理 z 分组的严格 D56 交叉事件（totals/planes/events）
* `validation.json`：独立 Validator 完整检查输出（含最小 3D 净空）
* `transition_stats.json`：中途换层统计
* `optimization_history.csv` / `joint_search_history.csv`：每次接受/拒绝记录
* `blocker_analysis.json`（D0）、`arc_crossing_analysis.json`（E0）、`arc_rebuild_results.json`（E）、`failed_attempts.json`
* `best_valid/`：最佳合法解 + config（SHA256）
## 验收标准（必须全部满足）
1. 1024/1024 真实连接，端口/连接器/接口高度不变；
2. 368 条人工 U 与基线逐字节一致；
3. 21 个高度、50 µm 层距、50 µm 真实三维净空、R15、玻璃 150×150×1 mm；
4. 所有换层为真实 R15 三维过渡（无 z 跳变/垂直折线）；
5. 真实同层交叉统计口径与基线一致（多高度按真实 z 分组）；
6. 独立 Validator：0 违规；所有正式接受解必须经过完整 1024 条全量验证。

