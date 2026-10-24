# 嵘兴无线电管理综合平台传输控制协议

**RX-RMCPTP**  
*Rongxing Radio Manage Comprehensive Platform Transfer Protocol*

| 项目   | 内容            |
| ---- | ------------- |
| 项目名称 | 嵘兴无线电监测综合管理平台 |
| 文档编写 | 杜小猛           |
| 版本号  | 1.9           |
| 更新日期 | 2012/7/5      |
| 公司   | 深圳市嵘兴实业发展有限公司 |

---

## 版本历史

| 版本  | 日期         | 作者  | 变更内容                                                     |
| --- | ---------- | --- | -------------------------------------------------------- |
| 1.9 | 2012/7/5   | 杜小猛 | 修正报文标志位：如果频率放大标志为1，表示频率被放大1000倍                          |
| 1.8 | 2011/12/14 | —   | 增加中频宽带测向(11/28)；增加调制模式识别；修正频谱分析的描述头定义错误                  |
| 1.7 | 2011/11/4  | —   | 增加IQ数字解调(29)、DDC解调(38)、空间谱测向(39)、多信道监听(40)、旋转云台(41)的协议定义 |
| 1.6 | 2010/12/06 | 杜小猛 | 添加宽带监测、能量探测、信号识别、信号告警                                    |
| 1.5 | 2009/11/12 | 杜小猛 | 调整频段扫描返回占用度的数据格式为(有效采样/总采样)；调整所有占用度数据长度为8字节              |
| 1.4 | 2009/8/24  | 杜小猛 | 添加通知消息接口                                                 |
| 1.3 | 2009/8/22  | 杜小猛 | 修正数据校验                                                   |
| 1.2 | 2009/8/21  | 杜小猛 | 添加音频数据格式                                                 |
| 1.1 | 2009/8/17  | 杜小猛 | 修正业务数据传输格式                                               |
| 1.0 | 2009/8/10  | 杜小猛 | 建立初稿                                                     |

---

## 目录

- [1 概述](#1-概述)
  - [1.1 缩略语](#11-缩略语)
  - [1.2 符号说明](#12-符号说明)
  - [1.3 名词解释](#13-名词解释)
  - [1.4 RX-RMCPT 连接说明](#14-rx-rmcpt-连接说明)
  - [1.5 请求应答时序](#15-请求应答时序)
- [2 通用数据报文结构](#2-通用数据报文结构)
  - [2.1 帧头说明](#21-帧头说明)
  - [2.2 报文数据类型](#22-报文数据类型)
- [3 数据分发请求报文](#3-数据分发请求报文)
- [4 监测业务数据报文](#4-监测业务数据报文)
  - [4.1 业务数据类型](#41-业务数据类型)
  - [4.2 业务数据描述头](#42-业务数据描述头)
  - [4.3 业务数据](#43-业务数据)
- [5 音频数据](#5-音频数据)
- [6 通知消息](#6-通知消息)
- [7 GPS 数据](#7-gps-数据)

---

## 1 概述

RX-RMCPTP 是嵘兴无线电管理综合平台的实时监测数据传输协议，基于 TCP/IP 实现。

### 1.1 缩略语

| 缩写        | 全称                                                             |
| --------- | -------------------------------------------------------------- |
| RX-RMCPTP | Rongxing Radio Manage Comprehensive Platform Transfer Protocol |
| RMCPT     | Radio Manage Comprehensive Platform Transfer                   |

### 1.2 符号说明

- **关键字**：粗体大写英文表示
- **可变项**：斜体小写英文表示

### 1.3 名词解释

| 术语            | 说明                                             |
| ------------- | ---------------------------------------------- |
| **测向统计时间**    | 设备读取测向数据的统计时间                                  |
| **监听统计时间**    | 设备读取音频数据的统计时间                                  |
| **监测统计时间**    | 其他监测数据的统计时间                                    |
| **校验和**       | 用于数据完整性的简单校验算法                                 |
| **数据单元**      | 包含业务数据的最小内容单元                                  |
| **客户段**       | 发送请求命令的通信方                                     |
| **中间服务**      | 提供持续数据的一体化平台服务                                 |
| **监测站设备组合标识** | 13位全国唯一编码 = 监测站码(8位) + 设备组合码(3位) + 同设备组合序号(2位) |

### 1.4 RX-RMCPT 连接说明

- 协议基于 **TCP/IP**
- 每个监测业务请求需要客户端建立新连接
- 客户端发起请求，中间服务器响应
- 业务处理完成后双方断开连接

### 1.5 请求应答时序

```
客户端                          服务器
  |                               |
  |------- TCP Connect ---------->|
  |                               |
  |------- 请求命令 ------------->|
  |                               |
  |<------ ACK + 数据响应 --------|
  |                               |
  |<------ 持续数据传输 ------------|
  |         ...                   |
  |                               |
  |------- 断开连接 -------------->|
```

---

## 2 通用数据报文结构

所有数据报文均以 18 字节的帧头开始。

### 2.1 帧头说明

#### 2.1.1 BYTE 图（18字节）

| 字节位置  | 字段        | 类型       | 说明                          |
|:-----:| --------- | -------- | --------------------------- |
| 1-4   | dwLength  | DWORD    | 报文总长度（字节）                   |
| 5-12  | tmStamp   | FILETIME | 报文产生时间戳                     |
| 13-14 | nVersion  | WORD     | 报文版本号（MAKEWORD(0,7)=0x0007） |
| 15    | nDataType | BYTE     | 报文数据类型                      |
| 16    | nFlags    | BYTE     | 报文标志                        |
| 17-18 | nCheckSum | WORD     | 头校验和                        |

#### 2.1.2 C++ 结构定义

```cpp
#pragma pack(push,1)
typedef struct tagRmcpFrame
{
    DWORD   dwLength;    // 报文长度(BYTE)
    FILETIME tmStamp;    // 报文产生时间
    WORD    nVersion;    // 报文版本号
    BYTE    nDataType;   // 报文数据类型
    BYTE    nFlags;      // 报文标志
    WORD    nCheckSum;   // 头校验和
} RMCPFRAME, *LPRMCPFRAME;
#pragma pack(pop)
```

#### 2.1.3 报文标志（nFlags）位定义

| 位   | 名称      | 说明                         |
|:---:| ------- | -------------------------- |
| 0   | 数据可丢弃标志 | 1=可丢弃，0=不可丢弃               |
| 1   | 电平数据标志  | 1=是电平数据                    |
| 2   | 场强数据标志  | 1=是场强数据                    |
| 3   | 频率放大标志  | 1=频率以1/10000Hz为单位，0=以Hz为单位 |
| 4-7 | 保留      | —                          |

#### 2.1.4 头校验和计算

1. 将时间和长度作为无符号短整型累加
2. 对无符号长整型结果进行两次半移位加法（将long视为两个short）
3. 对最终short值取反码即为校验和

### 2.2 报文数据类型（nDataType）

| 值   | 类型      | 说明        |
|:---:| ------- | --------- |
| 0   | 监测业务数据  | 业务数据      |
| 1   | 音频描述头   | 音频数据描述头   |
| 2   | 音频数据    | 音频数据流     |
| 3   | 分发请求    | 请求中间件发送数据 |
| 4   | 信息数据    | 文本信息      |
| 6   | 业务数据描述头 | 业务数据自描述头  |
| 7   | 视频数据描述头 | —         |
| 8   | 通知消息    | 中间服务通知    |
| 11  | GPS数据   | —         |

---

## 3 数据分发请求报文

客户端连接中间件时发送，用于请求数据分发。

**静态部分（72字节）：**

| 类型      | 关键字        | 长度  | 说明          |
| ------- | ---------- |:---:| ----------- |
| __int64 | nTaskid    | 8   | 请求分发数据的任务ID |
| char    | szUser[64] | 64  | 用户名         |

> **注意**：若 nTaskid == -1，则请求通知消息。

---

## 4 监测业务数据报文

### 4.1 业务数据类型（nBdType）

| ID (Hex) | ID (Dec) | 类型名称       | 说明          |
|:--------:|:--------:| ---------- | ----------- |
| 0x0A     | 10       | SGLFREQ    | 单频测量        |
| 0x0B     | 11       | IFANALYSIS | 中频分析        |
| 0x0C     | 12       | DF         | 单频测向        |
| 0x0D     | 13       | IFDF       | 中频测向        |
| 0x0E     | 14       | MSACN      | 离散扫描        |
| 0x0F     | 15       | FSCAN      | 频段扫描        |
| 0x10     | 16       | DSCAN      | 数字扫描        |
| 0x11     | 17       | PSCAN      | 频谱扫描（保留）    |
| 0x12     | 18       | SPANALYSIS | 频谱分析        |
| 0x13     | 19       | TDANALYSIS | 时域分析        |
| 0x14     | 20       | DFSEARCH   | 搜索测向        |
| 0x15     | 21       | SCANDF     | 频率测向        |
| 0x16     | 22       | MSEARCH    | 离散信号搜索      |
| 0x17     | 23       | FSEARCH    | 频段信号搜索      |
| 0x18     | 24       | ITU        | ITU测量       |
| 0x19     | 25       | WBMONDF    | 宽带监测测向      |
| 0x1A     | 26       | IFDFEXT    | 中频宽带测向      |
| 0x1B     | 27       | FHOP       | 跳频监测        |
| 0x1C     | 28       | WMON       | 宽带监测        |
| 0x1D     | 29       | DIGDEM     | IQ数字解调      |
| 0x1E     | 30       | BSCAN      | 宽带扫描        |
| 0x1F     | 31       | EDETN      | 能量探测        |
| 0x20     | 32       | DDF        | 离散测向        |
| 0x21     | 33       | SIGNALMEAS | 信号测量（TCI特殊） |
| 0x22     | 34       | MODREC     | 信号识别（黑鸟系统）  |
| 0x23     | 35       | SINA       | 信号告警（黑鸟系统）  |
| 0x24     | 36       | SMSG       | 和差信号（保留）    |
| 0x25     | 37       | IQ         | 保留（GPS占位）   |
| 0x26     | 38       | DDCDEM     | DDC解调       |
| 0x27     | 39       | SSDF       | 空间谱测向       |
| 0x28     | 40       | MULTICHAN  | 多信道监听       |
| 0x29     | 41       | ACDF       | 旋转云台        |
| 0x2A     | 42       | VIDEO      | 视频          |
| 0x2B     | 43       | DEMREC     | 调制模式识别      |
| 0x2C     | 44       | MULCHANANA | 双/多信道分析     |
| 0x2D     | 45       | SJAM       | 信号压制        |
| 0x2E     | 46       | ANALOGTV   | 模拟电视        |
| 0x2F     | 47       | DIGITALTV  | 数字电视        |
| 0x30     | 48       | TVBMP      | 电视图像        |
| 0x31     | 49       | DPX        | 荧光谱         |
| 0x32     | 50       | CAMERA     | 摄像头         |
| 0x33     | 51       | FREQMEAS   | 频点分析        |

### 4.2 业务数据描述头

当 nDataType = 6 时使用此描述头。

```cpp
#pragma pack(push,1)
typedef struct tagRmcpBusinessHead
{
    BYTE   nMonType;      // 业务数据类型
    DWORD  nArrays;        // 业务数组长度
    CHAR   pOffset[1];    // 业务偏移量占位指针
} RMCPBUSINESSHEAD, *LPRMCPBUSINESSHEAD;
#pragma pack(pop)
```

#### 4.2.1 各业务类型的描述头

##### SGLFREQ（单频测量）- 类型10

**静态部分：** nBdType=10, nArrays（ITU测量个数）, freq（__int64，Hz）, szAntenna[64]

**动态部分：** szITUName[16], fMinValue（float）, szUnit[10]

##### IFANALYSIS（中频分析）- 类型11

**静态部分：** nBdType=11, nArrays, freq, span, Ifbw

##### DF（单频测向）- 类型12

**静态部分：** nBdType=12, nArrays, freq

##### IFDF（中频测向）- 类型13

**静态部分：** nBdType=13, nArrays, freq, span, Ifbw

##### MSACN（离散扫描）- 类型14

**静态部分：** nBdType=14, nArrays（离散扫描点数）

**动态部分：** freq（__int64，每点频率）

##### FSCAN（频段扫描）- 类型15

**静态部分：** nBdType=15, nArrays（频段数）

**动态部分（每段）：** startfreq（起始频率）, endfreq（结束频率）, Step（步进）, nPoints（点数）

##### DSCAN（数字扫描）- 类型16

与 FSCAN 格式相同，仅业务类型不同。

##### SPANALYSIS（频谱分析）- 类型18

**静态部分：** nBdType=18, nArrays, curvecount, Indexclearwrite, Reflevel, Unit[10], nParamLen

**动态部分：** param字符串（格式：name:value+unit\n）

##### TDANALYSIS（时域分析）- 类型19

格式同 SPANALYSIS。

##### DFSEARCH（搜索测向）- 类型20

**静态部分：** nBdType=20, nArrays, DataType {0,1,2,3}

**动态部分（按DataType）：**

- DataType=1：频率, 带宽, IFBW
- DataType=2：DfLevel, Qulity, Azumith, Elevation, Compass, occ, thr
- DataType=3：Centerlevel, LevelCount, value[]

##### SCANDF（频率测向）- 类型21

**静态部分：** nBdType=21, nArrays, Compass

**动态部分（每数组）：** DfLevel, Qulity, Azumith, Elevation, thr, occ

##### MSEARCH（离散信号搜索）- 类型22

**静态部分：** nBdType=22, nArrays, ArrayDataType {0,1}

**动态部分（按ArrayDataType）：**

- ArrayDataType=0：value（short level）
- ArrayDataType=1：span, Ifbw, value（频谱曲线，无噪声/占用度）

##### FSEARCH（频段信号搜索）- 类型23

与 MSEARCH 类似。

##### ITU（ITU测量）- 类型24

**静态部分：** nBdType=24, nArrays, freq, szAntenna[64]

**动态部分：** szITUName[16], fMinValue, szUnit[10]

##### WBMONDF（宽带监测测向）- 类型25

**静态部分：** nBdType=25, Headtype {0,1,2}

- Headtype=0：全景频段头
- Headtype=1：部分测向头
- Headtype=2：中频频谱头

##### IFDFEXT（中频宽带测向）- 类型26

**静态部分：** nBdType=26, nArrays

**动态部分：** Centerfreq, span, Ifbw

##### DIGDEM（数字解调）- 类型29

**静态部分：** nBdType=29, nArrays, freq, IFBW, SIQPPacked, SampleRate, RefdBFS, GaindBTG

##### WMON（宽带监测）- 类型30

**静态部分：**

| 字段         | 类型       | 长度  | 说明          |
| ---------- | -------- |:---:| ----------- |
| nBdType    | byte     | 1   | 业务数据类型 = 30 |
| nArrays    | long     | 4   | 扫描段数        |
| level      | float    | 4   | 参考电平        |
| unit       | char[10] | 10  | 参考电平单位      |
| nResultNum | long     | 4   | 扩展数据数 = 9   |

**扩展数据标识（9组，每组20字节）：**

| 偏移      | 名称                 | 单位  |
| -------:| ------------------ | --- |
| 0-19    | TimeSymbol         | s   |
| 20-39   | FreqSymbol         | Hz  |
| 40-59   | RbwSymbol          | Hz  |
| 60-79   | AlarmsnrSymbol     | dB  |
| 80-99   | AlarmsRateSymbol   | kHz |
| 100-119 | AlarmdevSymbol     | kHz |
| 120-139 | ModemSymbol        | -   |
| 140-159 | AlarmconSymbol     | %   |
| 160-179 | PreciousTimeSymbol | s   |

**动态部分：**

| 字段         | 类型    | 长度  | 说明   |
| ---------- | ----- |:---:| ---- |
| nStartFreq | float | 4   | 开始频率 |
| nStopFreq  | float | 4   | 结束频率 |
| rbw        | float | 4   | 带宽   |

**业务数据格式（dataType）：**

- dataType=0：fStartFreq, fStopFreq, Overlap, value[]
- dataType=1：AlarmDesc[32], confidence, subtime

##### EDETN（能量探测）- 类型31

**静态部分：**

| 字段         | 类型       | 长度  | 说明          |
| ---------- | -------- |:---:| ----------- |
| nBdType    | byte     | 1   | 业务数据类型 = 31 |
| nArrays    | long     | 4   | 扫描段数        |
| level      | float    | 4   | 参考电平        |
| unit       | char[10] | 10  | 参考电平单位      |
| nResultNum | long     | 4   | 扩展数据数 = 5   |

**扩展数据标识（5组，每组20字节）：**

| 偏移    | 名称                 | 单位  |
| -----:| ------------------ | --- |
| 0-19  | TimeSymbol         | s   |
| 20-39 | FreqSymbol         | Hz  |
| 40-59 | RbwSymbol          | Hz  |
| 60-79 | alarmamplSymbol    | dBm |
| 80-99 | PreciousTimeSymbol | s   |

**动态部分：**

| 字段         | 类型    | 长度  | 说明   |
| ---------- | ----- |:---:| ---- |
| nStartFreq | float | 4   | 开始频率 |
| nStopFreq  | float | 4   | 结束频率 |
| rbw        | float | 4   | 带宽   |

**业务数据格式：** 同 WMON（dataType {0,1}）

##### SINA（信号告警）- 类型35

**静态部分：**

| 字段         | 类型       | 长度  | 说明          |
| ---------- | -------- |:---:| ----------- |
| nBdType    | byte     | 1   | 业务数据类型 = 35 |
| nArrays    | long     | 4   | 扫描段数        |
| level      | float    | 4   | 参考电平        |
| unit       | char[10] | 10  | 参考电平单位      |
| nResultNum | long     | 4   | 扩展数据数 = 9   |

**扩展数据标识：** 同 WMON（9组）

**业务数据格式：** 同 WMON（dataType {0,1}），dataType=1时包含 AlarmDesc[32] 告警描述

##### MODREC（信号识别）- 类型34

**静态部分：**

| 字段         | 类型       | 长度  | 说明          |
| ---------- | -------- |:---:| ----------- |
| nBdType    | byte     | 1   | 业务数据类型 = 34 |
| nArrays    | long     | 4   | = 0         |
| level      | float    | 4   | 参考电平        |
| unit       | char[10] | 10  | 参考电平单位      |
| nResultNum | long     | 4   | 扩展数据数 = 9   |
| nCentFreq  | __int64  | 8   | 中心频率        |
| nSpan      | __int64  | 8   | 跨距          |
| nIFBW      | __int64  | 8   | 带宽          |

**业务数据格式：** 同 WMON（dataType {0,1}），dataType=1时 AlarmDesc[32] 为调制类型描述

##### DDCDEM（DDC解调）- 类型38

**静态部分：** nBdType=38, nArrays, freq, Level, demfreq, Demifbw

**动态部分：** value[]（频谱电平 × 100）

##### SSDF（空间谱测向）- 类型39

**静态部分：** nBdType=39, nArrays, nType {0,1}

- nType=0：测向数据（nMonLevel, compass, DfLevel, Qulity, Azumith, Elevation）
- nType=1：频谱数据（nLevel数组）

##### MULTICHAN（多信道监听）- 类型40

**静态部分：** nBdType=40, nArrays, nOffset, nCdType {0,2}

**动态部分：**

- nCdType=0：监测数据（freq, Level, value[]）
- nCdType=2：音频数据（AudioData）

##### ACDF（旋转云台）- 类型41

**静态部分：** nBdType=41, nArrays, Level, DfLevel, Qulity, Azumith, Elevation, compass

##### DEMREC（调制模式识别）- 类型43

**静态部分：** nBdType=43, nArrays, cType {0,1,2,3,4}

- cType=0：频谱数据
- cType=1：ITU数据
- cType=2：调制识别数据（char数组）
- cType=3：调制方式 + 概率
- cType=4：符号率（float）

**调制方式类型（SignalType_HG 枚举）：**

| 值   | 调制方式         |
|:---:| ------------ |
| 0   | CW           |
| 1   | 2ASK         |
| 2   | 4ASK         |
| 3   | BPSK         |
| 4   | QPSK         |
| 5   | OQPSK        |
| 6   | Unknown      |
| 7   | 2FSK         |
| 8   | 4FSK         |
| 9   | 8FSK         |
| 10  | 16/64/256QAM |
| 11  | FM           |
| 12  | AM           |
| 13  | PI_4_QPSK    |

##### MULCHANANA（双/多信道分析）- 类型44

**静态部分：** nBdType=44, nArrays, cType {0,1,2}

- cType=0：频谱数据（channel byte + level + value[]）
- cType=1：ITU数据（channel byte + value[]）
- cType=2：调制识别（channel byte + confidence + char）

##### DPX（荧光谱）- 类型49

**静态部分：** nBdType=49, nArrays, nTotalPoints, nSampleRate, nRBW, dRate, nMinLevel

**动态部分：** DPXDATA（160位掩码 + 计数数据）

##### FREQMEAS（频点分析）- 类型51

通用协议，单频点返回 ITU/频谱/IQ/音频数据。

**FLAGS 位定义（32位）：**

| 位     | 字段      |
|:-----:| ------- |
| 0     | 信道号     |
| 1     | 中心频率    |
| 2     | 电平      |
| 3     | 场强      |
| 4     | 测向电平    |
| 5     | 测向角度    |
| 6     | 测向质量    |
| 7     | 仰角      |
| 8     | 指南针     |
| 9     | ITU测量结果 |
| 10    | IQ数据    |
| 11    | 调制方式识别  |
| 12    | GPS结果   |
| 13    | TDOA结果  |
| 14    | 频谱      |
| 15    | 此包含描述头  |
| 16-31 | 保留      |

### 4.3 业务数据

当 nDataType = 0 时使用业务数据报文。

```cpp
#pragma pack(push,1)
typedef struct tagRmcpBusinessData
{
    BYTE   nBdType;     // 业务数据类型
    SHORT  nFlags;      // 业务数据标志
    DWORD  nArrays;    // 业务数组个数
    DWORD  nOffset;    // 业务数组偏移
    CHAR   pOffset[1]; // 业务数组偏移占位
} RMCPBUSINESSDATA, *LPRMCPBUSINESSDATA;
#pragma pack(pop)
```

**业务数据标志（nFlags）位 0-15：**

| 位    | 说明     |
|:----:| ------ |
| 0    | 基础业务数据 |
| 1    | 自动噪声数据 |
| 2    | 占用度数据  |
| 3    | 手动噪声数据 |
| 4-15 | 保留     |

#### 4.3.1 各业务数据详情

##### SGLFREQ（单频测量）

- **频率**：__int64，单位Hz（除非nFlags bit3=1则为1/10000Hz）
- **电平值**：实际值 × 100（如 -70.5 dBm 存储为 -7050）

##### 中频分析 / 单频测向 / 中频测向

与上述类似格式，包含频率和电平信息。

##### 频段扫描 / 数字扫描

返回数据格式：有效采样 / 总采样（高4字节=有效采样，低4字节=总采样）

##### 离散扫描

每点返回频率和电平。

##### 频谱分析 / 时域分析

返回频谱/时域曲线数据，包含参考电平、频率范围等。

##### 搜索测向 / 频率测向 / 离散测向

返回测向数据：电平、质量、方位角、仰角、罗盘、占用度、阈值等。

##### 宽带监测 / 能量探测

返回起始频率、终止频率、重叠度、采样值数组。

##### 信号告警

包含告警描述 AlarmDesc[32]、置信度 subtime。

##### 信号识别

返回调制方式描述和置信度。

---

## 5 音频数据

- **音频描述头**：nDataType = 1
- **音频数据**：nDataType = 2
- 音频数据格式未定，对网络传输透明

---

## 6 通知消息

nDataType = 8

```cpp
#pragma pack(push,1)
typedef struct tagRmcpNotifyFrame
{
    RMCPFRAME rmcpFrame;
    SHORT nServiceID;    // 服务ID
    SHORT nNotifyID;    // 通知消息ID
    INT64 nTaskID;      // 任务ID
} RMCPNOTIFYFRAME, *LPRMCPNOTIFYFRAME;
#pragma pack(pop)
```

---

## 7 GPS 数据

nDataType = 11

```cpp
#pragma pack(push,1)
typedef struct tagRmcpGPSFrame
{
    RMCPFRAME rmcpFrame;
    UINT  nStationID;    // 监测站ID
    FLOAT nLongitude;   // 经度
    FLOAT nLatitude;    // 纬度
} RMCGPSRAME, *LPRMCGPSRAME;
#pragma pack(pop)
```

---

## 附录：关键实现要点

1. **字节序**：所有多字节整数使用小端序（Little-Endian）
2. **结构对齐**：所有 C++ 结构使用 `#pragma pack(push,1)` 进行1字节对齐
3. **频率单位**：除非nFlags bit3置1，否则频率以Hz为单位
4. **电平值存储**：大多数电平值存储为 实际值 × 100（如 -70.5 dBm 存储为 -7050）
5. **占用度格式**：高4字节 = 有效采样数，低4字节 = 总采样数
6. **连接模型**：一次请求 = 一个TCP连接 = 一次响应 = 断开
