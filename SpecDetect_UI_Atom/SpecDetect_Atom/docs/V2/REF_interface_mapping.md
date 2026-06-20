# SOAP-RMCP Interface Mapping (参考)

> 从 settings.json 中提取，保留为开发参考。代码中不使用此配置。

## soap_to_rmcp

| funcid | SOAP 接口 | RMCP nBdType | RMCP 类型 | 备注 |
|--------|-----------|-------------|-----------|------|
| 11 | B_SglFreqMeas | 0x0E | SGLFREQ | demodmode=FM 时为 0x0B (IFANALYSIS)；文档写 0x0A，实测不符 |
| 13 | B_SglFreqDF | - | - | 待实测 |
| 14 | B_MScan | 0x0E | SGLFREQ | 文档写 MSCAN，实测不符 |
| 15 | B_FScan | 0x0F / 0x10 | FSCAN / DSCAN | 同时返回两种数据 |
| 16 | B_PScan | 0x10 / 0x06 | DSCAN / RESPONSE | 文档写 0x11/0x01，实测不符 |
| 21 | B_FScanDF | - | - | 待实测 |
| 25 | B_WBDF | - | - | 待实测 |
| 32 | B_MScanDF | - | - | 待实测 |

## rmcp_to_soap

| nBdType | RMCP 名称 | SOAP funcid | SOAP 接口 |
|---------|-----------|-------------|-----------|
| 0x0B | IFANALYSIS | 11 | B_SglFreqMeas |
| 0x0E | SGLFREQ | 14 | B_MScan |
| 0x0F | FSCAN | 15 | B_FScan |
| 0x10 | DSCAN | 15 | B_FScan |
| 0x01 | PSCAN | 16 | B_PScan |

## 关键发现

1. **两套独立编号体系** — SOAP funcid 与 RMCP nBdType 无直接数学映射
2. **funcid=11 复用** — B_SglFreqMeas + demodmode=FM 时返回 IFANALYSIS(0x0B)
3. **funcid=14 异常** — B_MScan 实测返回 SGLFREQ(0x0E) 而非文档定义的 MSCAN
4. **funcid=15 双回调** — B_FScan 同时返回 FSCAN(0x0F) 和 DSCAN(0x10)
5. **funcid=16 异常** — B_PScan 实测返回 DSCAN(0x10)，与文档 0x11/0x01 均不符
