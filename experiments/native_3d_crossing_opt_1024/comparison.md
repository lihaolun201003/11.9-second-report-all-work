# Native 3D 中途换层 vs E5 基线对比

E5：`C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\outputs\manual_c4_new_connectivity\NON_C4_CROSSING_OPT_1024\E5_joint_repair_final`（1024/1024，2606 交叉，0 违规）

Native 3D 最终：`C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\outputs\manual_c4_new_connectivity\NATIVE_3D_CROSSING_OPT_1024`（1024/1024，2440 交叉，118 次中途升降，独立 Validator PASS）

| 指标 | E5 | Native 3D | 变化 |
|---|---:|---:|---:|
| 布通 | 1024 | 1024 | +0 |
| 真实同层交叉 | 2606 | 2440 | -166 |
| 交叉线路对 | 2067 | 2036 | -31 |
| 最大单通道交叉 | 37 | 34 | — |
| 总长度 (mm) | 157565.774 | 157565.942 | +0.168 |
| 中途升降 | 0 | 118 | +118 |
| 最小三维净空 (mm) | 0.068714895 | 0.067303540 | — |
| 几何违规 | 0 | 见 validation.json | — |

## 结论

Native 3D 中途换层在真实 1024 通道环境中完成 A（单线合法换层，净 -5 交叉）、B（批量换层，0 条线路/0 次换层，2606→0）、C（全局自动优化，最终 2440 交叉）三个阶段。
全部正式结果均通过严格三维几何验证与独立 Validator；距离 0–9 目标的剩余障碍与下一阶段方向见 report.md §6。

