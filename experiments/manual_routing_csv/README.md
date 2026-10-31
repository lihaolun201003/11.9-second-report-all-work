# 新人工布线 CSV（manual routing exports, section 2）

本目录收录 `manual_z1_router` 工具导出的**人工布线连接表（section 2）**，仅包含
端口/行列/坐标/层标签等布线分配信息，不包含生成的三维几何。

| 文件 | 数据行数 | 说明 |
|---|---:|---|
| `manual_z1_c4_full_section2.csv` | 512 | Z1 部分人工布线分配（section 2 全量）；`relation`: `opposite` 256 / `same` 256；`layer` 均为 `z1`；源边分布 N133 / S123 / W128 / E128 |
| `manual_z2_c4_full_section2.csv` | 128 | Z2 部分人工布线分配（section 2）；`relation`: `adjacent` 100 / `same` 28；`layer` 字段均为 `z1`（沿用导出工具的层标签列）；源边分布 N79 / E31 / W18 |

## 字段

```
route_id, source_side, source_connector, source_row, source_column, source_channel,
target_side, target_connector, target_row, target_column, target_channel,
relation, source_port_id, target_port_id,
source_x_mm, source_y_mm, target_x_mm, target_y_mm, layer
```

- `route_id`：连接编号（与 1024 通道连接表一致）；
- `source_*` / `target_*`：所在边、连接器、行列、通道；
- `relation`：`opposite` / `same` / `adjacent`（连接类别）；
- `source_port_id` / `target_port_id`：端口标识，如 `N01:1:1`；
- `source_x_mm` / `source_y_mm` / `target_x_mm` / `target_y_mm`：端口坐标（mm，板 150×150）；
- `layer`：导出工具给出的层标签。

## 来源与用途

- 本地来源：`OpticalWaveguideRouter2D/manual_z1_router/data/exports/`；
- 用途：人工布线方案的数据归档与后续按层生成真实三维几何（S 型升降、R15 曲率、
  0.08 mm 净空）时作为连接/分层输入；
- 本目录**只含布线表**，不含三维几何与验证结果；几何与交叉统计见仓库
  `experiments/` 下的相应实验目录。

> 数据仅包含板级连接关系与端口坐标，不含个人信息、路径或访问凭证。
