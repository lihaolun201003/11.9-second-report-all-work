# F2 reworked 代码（Z1 非对称 + Z2 严格 C4 增量合法搜索）

| 文件 | 作用 |
|---|---|
| `run_f2.py` | 冻结同判据 oracle（复用 `validate_l3d_multi` 的三维采样与线段距离）、从 E1 合法布局增量修改 Z1 目标层、Z2 128 个严格 C4 四元组优化、分块应用 + 每块全量冻结验证、检查点保存 |
| `finalize.py` | 目标完成率优先的附加合法轨道、联合局部重优化轮次、F3 邻边选择性抬升尝试、comparison 与图件 |
| `finish_artifacts.py` | 17 张规定图件（逐层、NS/EW 分层、Z2 四元组分、窗口、热点、前后对比）、诊断与最终数字汇总 |

## 关键点

- **合法性判定与冻结验证器一致**：`FrozenOracle` 直接调用冻结验证器
  `validate_l3d_multi` 的 `_parse_route` / `_build_3d_segment_store` /
  `_segment_segment_closest`，过渡段 0.02 mm、平铺 0.1/0.02 mm 采样，
  `limit = 0.08 - 1e-7`；候选必须同时通过 D56 同层检查。
- **不破坏已有合法几何**：以 E1 3,594 合法解为起点，仅改目标层不满足的 260 条
  Z1 对边路线；分 13 块应用，每块后跑完整冻结验证（13/13 通过）。
- **Z2 严格 C4**：128 个四元组整体调整（层 + 窗口），反向成员自动交换起终点窗口，
  独立 C4 验证 PASS（最大 XYZ 偏差 2.84e-14 mm）。
- **局部联合优化真实执行**：Z2 四元组重优化、Z1 窗口精修、联合轮次均记录
  `stats`（候选/接受/验证次数）与合法检查点。

## 复现

```bash
python -m four_side_1024.f2fix.run_f2            # 增量合法 F2 搜索
python -m four_side_1024.f2fix.finalize          # 附加合法轨道 + F3 + comparison
python -m four_side_1024.f2fix.finish_artifacts  # 规定图件 + 最终数字
```
