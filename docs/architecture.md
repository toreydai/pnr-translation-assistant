# 自然语言到 PNR 机器指令翻译系统

## 1. 目的

本文档设计一个使用 Amazon Bedrock 内置 Kimi 模型的自然语言到 PNR 机器指令翻译系统。

设计目标不是让大模型直接生成最终可执行指令，而是让模型完成语义理解、实体抽取、候选指令排序和缺槽判断。最终 PNR 机器指令由确定性规则、DSL schema、校验器和渲染器生成，确保结果可解释、可审计、可补偿、可持续评估。

## 2. 设计原则

- Bedrock 是唯一大模型入口，应用只通过 Amazon Bedrock Runtime 调用 Bedrock 内置 Kimi 模型。
- 主链路使用 `moonshotai.kimi-k2.5`，复杂复核链路使用 `moonshot.kimi-k2-thinking`。
- 模型只输出结构化中间表示，不直接输出最终 PNR 机器指令。
- 最终指令由确定性 `PNR Command Renderer` 生成。
- 所有结果必须经过 schema 校验、语法校验、业务规则校验、权限校验和风险策略校验。
- 高风险、低置信度、多意图、缺字段请求必须进入澄清或人工审核。
- 全链路保留审计记录，支持问题追溯和离线评估。
- 不假设 PNR/GDS 操作具备事务回滚能力；对已执行动作采用执行前校验、状态锁、补偿操作和人工恢复流程降低风险。

## 3. 范围

### 3.1 本期范围

- 支持高频 PNR 操作的自然语言翻译。
- 支持指令预览和用户确认。
- 支持低风险指令的自动执行开关。
- 支持人工审核流转。
- 支持知识库检索、术语映射、样例召回。
- 支持离线评估和失败样本回流。

### 3.2 非本期范围

- 不直接替代现有 PNR/GDS 系统。
- 不让模型绕过校验直接执行指令。
- 不在模型提示词中长期保存敏感旅客数据。
- 不覆盖所有航司、所有 GDS、所有票务操作；初期只做白名单意图。

## 4. 总体架构

```text
用户 / 客服系统
  |
  v
API Gateway / ALB
  |
  v
AuthN / AuthZ
  |
  v
PNR Translation Service
  |
  +--> PII Redactor
  |
  +--> Context Loader
  |      +--> PNR Context Store
  |      +--> Current PNR State
  |
  +--> Retrieval Service
  |      +--> Built-in Term Dictionary / S3 JSON Terms
  |      +--> Optional OpenSearch / Bedrock Knowledge Bases
  |      +--> Command Library
  |      +--> Term Dictionary
  |      +--> Example Library
  |
  +--> Bedrock Runtime
  |      +--> moonshotai.kimi-k2.5
  |      +--> moonshot.kimi-k2-thinking
  |
  +--> PNR DSL Validator
  |
  +--> PNR Command Renderer
  |
  +--> Risk Policy Engine
  |
  +--> Human Review / Confirmation
  |
  +--> Audit Store
  |
  +--> PNR/GDS Adapter
  |
  v
Audit Log / Metrics / Evaluation Dataset
```

## 5. 核心模块

### 5.1 PNR Translation Service

主业务编排服务，负责：

- 接收自然语言请求；
- 加载当前 PNR 上下文；
- 调用脱敏模块；
- 调用检索服务召回候选知识；
- 调用 Bedrock Kimi 模型生成结构化中间表示；
- 调用校验器和渲染器生成最终指令；
- 根据风险策略决定预览、追问、人工审核或执行。

建议使用 ECS Fargate 或 EKS 部署。若请求量较低、调用链较短，也可以使用 Lambda，但如果 PNR 会话需要较强状态管理，优先 ECS/EKS。

### 5.2 AuthN / AuthZ

认证和授权层负责确认调用方身份、租户、角色、权限范围和审批能力。客户端不得在请求体中声明执行人或审核人，执行人、审核人、租户和权限信息必须来自认证上下文，例如企业 SSO、OIDC/JWT claims、IAM Identity Center 或内部权限服务。令牌不含 roles/groups claim 时不授予任何默认角色，请求直接拒绝（fail-closed）。

权限模型至少包含：

- `translator`：允许发起翻译和查看脱敏预览；
- `executor`：允许确认执行低风险或中风险白名单指令；
- `reviewer`：允许审核高风险或低置信度指令；
- `admin`：允许维护指令 schema、规则库和白名单；
- `auditor`：允许查看审计记录，默认不能执行业务操作。

执行前必须校验：

- 用户是否属于当前租户；
- 用户是否有当前 PNR 或业务队列的访问权限；
- intent 是否在该用户角色的允许范围内；
- 是否满足 maker-checker 要求，即发起人和审核人不能是同一个人；
- 审批状态是否仍然有效；
- PNR 状态版本是否与翻译时一致。

### 5.3 PII Redactor

负责模型调用前的数据最小化和脱敏：

- 旅客姓名替换为 `PAX_NAME_1`；
- 证件号替换为 `DOC_ID_1`；
- 手机号替换为 `PHONE_1`；
- 邮箱替换为 `EMAIL_1`；
- PNR 编号替换为 `PNR_1`。

脱敏模块必须生成映射表，并只在服务端内存或加密存储中短期保存。最终可执行指令在写入加密安全存储前用映射表回填真实值（去脱敏），完整性 hash 也对该真实指令计算；对外 API 与普通日志只暴露脱敏预览。证件号占位采用「6–20 位大写字母数字且至少含一位数字」的规则，避免误伤机场/航司/SSR 等纯字母码。

### 5.4 Retrieval Service

负责从知识库中召回和排序候选资料。

召回来源：

- 指令库：机器指令模板、字段要求、示例。
- 术语库：行业术语、缩写、同义词、中文表达。
- 业务规则库：航司、区域、GDS、内部审批规则。
- 历史样例库：已审核通过的自然语言到中间表示样例。

召回方式：

- 精确检索：指令码、SSR 代码、航司二字码、机场三字码。
- 语义检索：自然语言相似样例。
- 规则过滤：根据初步意图、航司、GDS、区域、生效时间过滤。

检索采用两阶段策略：

1. 轻量初判：用规则、关键词、术语词典或小模型先得到候选 intent shortlist。
2. 受限召回：根据候选 intent、航司、GDS、区域和生效时间过滤知识库，再做精确检索和语义检索。

默认实现使用内置术语词典和可导入的 S3/本地 JSON 术语表。OpenSearch Service、OpenSearch Serverless 或 Bedrock Knowledge Bases 不是最小可运行链路的必需组件；当术语表、历史样例和同义表达规模扩大，需要向量召回、相似样例检索和 rerank 时再启用。

### 5.5 Bedrock Kimi Model Adapter

模型适配层统一封装 Bedrock Runtime 调用。

主模型：

```text
modelId: moonshotai.kimi-k2.5
用途: 意图识别、实体抽取、候选指令排序、缺槽判断、解释生成
```

复核模型：

```text
modelId: moonshot.kimi-k2-thinking
用途: 复杂请求复核、规则冲突分析、低置信度判断、多意图拆分
```

模型输出必须是 JSON，不允许返回自由文本作为系统输入。应用层必须对模型响应执行严格 schema 校验，任何未通过校验的响应都不能进入指令渲染链路。

> 实现说明：当前原型在 Bedrock 不可用（未开通模型访问或区域不支持）时走确定性兜底，基于检索 hints 拼出中间表示，仅用于本地测试和离线演示，不代表生产质量。生产部署需关闭兜底或将其降级为「直接转人工」。

模型输出示例：

```json
{
  "intent": "add_ssr_meal",
  "entities": {
    "passenger_ref": "P1",
    "segment_ref": "S2",
    "ssr_code": "VGML",
    "airline": "MU"
  },
  "missing_fields": [],
  "risk_level": "medium",
  "confidence": 0.91,
  "evidence_ids": ["cmd:add_ssr_meal", "term:vgml"],
  "clarification_question": null
}
```

模型输出处理规则：

- 使用固定 prompt template version 和 JSON Schema version；
- 解析失败时最多重试一次，并在重试提示词中只要求修复 JSON 格式；
- 重试后仍失败，状态置为 `model_output_invalid` 并转人工审核；
- 字段缺失时不得猜测，状态置为 `need_clarification`；
- 输出中包含 schema 未定义字段时丢弃该字段并记录告警；
- evidence_ids 必须能在当前知识库版本中解析，否则降低置信度并转人工审核；
- 所有模型响应只作为候选结构化输入，不能直接作为最终指令或审计事实。

### 5.6 PNR DSL Validator

校验结构化中间表示是否满足指令 schema。

校验内容：

- intent 是否在白名单内；
- required fields 是否完整；
- 字段格式是否正确；
- 枚举值是否允许；
- 航段、旅客序号是否存在；
- 当前 PNR 状态是否允许该操作；
- 业务规则是否允许自动执行；
- 模型证据是否支持该意图。

### 5.7 PNR Command Renderer

根据 DSL schema 渲染最终机器指令。

示例 schema：

```yaml
intent: add_ssr_meal
description: 添加特殊餐食 SSR
required_fields:
  - passenger_ref
  - segment_ref
  - ssr_code
  - airline
enum_constraints:
  ssr_code: [VGML, AVML, CHML, BBML]
format_constraints:
  passenger_ref: "^P[0-9]+$"
  segment_ref: "^S[0-9]+$"
render_template: "SSR {ssr_code} {airline} HK1/{passenger_ref}/{segment_ref}"
risk_policy:
  level: low
  auto_execute: true
  require_review_when_confidence_below: 0.85
```

渲染后必须做反解析，确认反解析结果和中间表示一致。

### 5.8 Risk Policy Engine

风险策略用于决定处理方式：

```text
低风险 + 高置信度 + 白名单 intent -> 可自动执行
中风险 + 高置信度 -> 用户确认后执行
低置信度 / 缺字段 -> 追问用户
高风险 / 规则冲突 / 多意图 -> 人工审核
禁止 intent -> 拒绝执行并解释原因
```

高风险操作包括：

- 取消航段；
- 改签；
- 涉及票价、税费、退票、支付；
- 修改证件信息；
- 涉及多人、多航段批量操作；
- 当前 PNR 状态不稳定或刚被外部系统修改。

自动执行只允许同时满足以下条件：

- risk level 为 `low`；
- intent 在自动执行白名单；
- confidence 达到当前 intent 的阈值；
- DSL 校验、业务规则校验、权限校验全部通过；
- PNR 状态版本未变化；
- 当前用户角色允许执行该 intent；
- 当前租户策略允许自动执行；
- 请求带有真实 PNR 上下文。缺省（未提供）上下文时不伪造旅客/航段，且一律禁止自动执行——因为无法校验旅客/航段是否真实存在。

`medium` 风险指令不能自动执行，必须由用户确认；`high` 风险指令必须人工审核。

## 6. 关键流程

### 6.1 翻译预览流程

```text
1. 用户输入自然语言请求
2. 系统加载当前 PNR 上下文
3. PII Redactor 脱敏
4. 轻量初判生成候选 intent shortlist
5. Retrieval Service 基于候选 intent 召回指令、术语、样例和规则
6. 调用 moonshotai.kimi-k2.5 生成结构化中间表示
7. JSON schema 校验和模型响应失败处理
8. PNR DSL Validator 校验字段、规则和状态
9. PNR Command Renderer 生成脱敏指令预览
10. Risk Policy Engine 判断是否需要确认或人工审核
11. 返回预览结果、解释和下一步动作
```

### 6.2 追问流程

触发条件：

- 必填字段缺失；
- 用户表达存在歧义；
- 多个候选意图分数接近；
- 召回证据不足；
- 当前 PNR 状态无法唯一定位旅客或航段。

返回示例：

```json
{
  "status": "need_clarification",
  "question": "请确认要为第几个旅客添加素食餐？",
  "missing_fields": ["passenger_ref"],
  "candidate_values": ["P1", "P2"]
}
```

### 6.3 人工审核流程

触发条件：

- 风险等级为 high；
- 置信度低于阈值；
- 复核模型建议人工审核；
- DSL 校验通过但业务规则存在冲突；
- 用户权限不足但可申请审批。

人工审核台展示：

- 原始用户输入；
- 脱敏后的模型输入；
- 当前 PNR 上下文摘要；
- 召回证据；
- 模型结构化输出；
- 校验结果；
- 指令预览；
- 风险解释。

审核动作（`/approve`、`/reject`）由 `reviewer`/`admin` 角色发起，并强制 maker-checker：审核人不能是该翻译的发起人，否则拒绝。`approve` 后翻译状态由 `manual_review` 转为 `ready_for_confirm`（随后才可执行），`reject` 转为 `rejected`；两者都会记录审核人、审核时间和审核意见。

### 6.4 执行流程

```text
1. 用户确认或审核通过
2. 系统从认证上下文获取执行人、租户和角色
3. 校验用户权限、maker-checker、审批状态和 intent 白名单
4. 系统检查幂等键：同一 `idempotency_key` 重放时返回首次执行结果（同一 `execution_id`），不重复执行
5. 比对翻译时状态版本，传入的 `pnr_context_version` 与翻译记录不一致则拒绝（`stale pnr_context_version`）
6. 重新加载 PNR 当前状态
7. 若状态变化，重新校验或要求重新生成
8. 调用 PNR/GDS Adapter 执行指令
9. 记录执行结果
10. 将成功/失败样本写入评估回流队列

> 实现说明：原型的执行步骤完成权限、状态版本、幂等校验后只写入执行记录，**未真正调用 GDS**；接入生产需替换为真实 PNR/GDS Adapter，并实现执行前状态锁与补偿。
```

## 7. API 设计

### 7.1 翻译接口

```http
POST /v1/pnr/translate
```

请求：

```json
{
  "session_id": "s-001",
  "pnr_context_id": "ctx-001",
  "user_text": "给第一个旅客第二段加一个东航素食餐",
  "execution_mode": "preview"
}
```

响应：

```json
{
  "translation_id": "tr-001",
  "status": "ready_for_confirm",
  "intent": "add_ssr_meal",
  "intermediate": {
    "passenger_ref": "P1",
    "segment_ref": "S2",
    "ssr_code": "VGML",
    "airline": "MU"
  },
  "command_preview_redacted": "SSR VGML MU HK1/P1/S2",
  "confidence": 0.91,
  "risk_level": "medium",
  "requires_manual_review": false,
  "explanations": [
    "识别为添加特殊餐食 SSR",
    "VGML 对应素食餐",
    "P1 为第一个旅客，S2 为第二航段"
  ]
}
```

### 7.2 执行接口

```http
POST /v1/pnr/execute
```

请求：

```json
{
  "translation_id": "tr-001",
  "idempotency_key": "idem-001",
  "pnr_context_version": "v12"
}
```

响应：

```json
{
  "status": "executed",
  "execution_id": "exe-001",
  "command_redacted": "SSR VGML MU HK1/P1/S2",
  "pnr_context_version": "v13"
}
```

执行人、租户、角色和权限范围从认证上下文读取，不允许客户端通过请求体传入。真实可执行指令只由执行服务通过 `secure_command_ref` 在服务端读取，不在普通 API 响应中返回。

### 7.3 审核接口

```http
POST /v1/pnr/reviews/{review_id}/approve
POST /v1/pnr/reviews/{review_id}/reject
```

审核接口必须记录审核人、审核时间、审核意见和最终动作。审核人从认证上下文读取，不允许客户端通过请求体传入。

## 8. 数据模型

### 8.1 TranslationRecord

```json
{
  "translation_id": "tr-001",
  "session_id": "s-001",
  "pnr_context_id": "ctx-001",
  "pnr_context_version": "v12",
  "user_text_redacted": "给 P1 第二段加一个 MU 素食餐",
  "intent": "add_ssr_meal",
  "intermediate": {},
  "command_preview_redacted": "SSR VGML MU HK1/P1/S2",
  "command_hash": "sha256:...",
  "secure_command_ref": "s3://secure-command-store/tr-001",
  "confidence": 0.91,
  "risk_level": "medium",
  "status": "ready_for_confirm",
  "model_id": "moonshotai.kimi-k2.5",
  "evidence_ids": ["cmd:add_ssr_meal", "term:vgml"],
  "created_at": "2026-06-16T00:00:00Z"
}
```

字段说明：

- `command_preview_redacted`：只保存脱敏后的指令预览，可用于普通业务日志和审核台展示。
- `command_hash`：用于证明执行指令未被篡改。
- `secure_command_ref`：指向加密短期存储中的真实可执行指令，只有执行服务角色可读。

### 8.2 CommandDefinition

```json
{
  "intent": "add_ssr_meal",
  "version": "2026-06-16",
  "required_fields": ["passenger_ref", "segment_ref", "ssr_code", "airline"],
  "render_template": "SSR {ssr_code} {airline} HK1/{passenger_ref}/{segment_ref}",
  "risk_policy": {
    "level": "low",
    "auto_execute": true,
    "min_confidence": 0.85
  },
  "status": "active"
}
```

## 9. 存储设计

- DynamoDB：翻译任务状态、执行状态、幂等键、会话状态。
- S3：原始知识文档、评估集、审计归档、批量导入文件。
- S3 加密短期存储：真实可执行指令和 PII 映射表，配置严格 TTL 和访问控制。
- S3 JSON 术语表：机场、城市、国家、航司和别名映射。
- 可选 OpenSearch：指令库、术语库、样例库、向量索引。
- Secrets Manager：PNR/GDS 系统凭证。
- CloudWatch Logs：应用日志和模型调用摘要。

敏感字段必须加密存储，日志中默认只保存脱敏文本。真实可执行指令不得进入普通应用日志、检索索引或评估集。

## 10. 安全设计

- IAM 最小权限，只允许应用角色调用指定 Bedrock Kimi 模型。
- 使用 VPC Endpoint 访问 Bedrock、S3、DynamoDB；如启用 OpenSearch，再配置对应网络访问边界。
- KMS 加密所有持久化数据。
- 模型输入默认脱敏，禁止把明文证件号、手机号、邮箱直接送入模型。
- 审计日志不可被普通业务角色修改。
- 执行接口必须校验认证上下文、用户权限、审批状态、maker-checker、租户隔离和幂等键。
- 高风险操作必须保留人工审核记录。
- 真实可执行指令和 PII 映射表使用独立 KMS key 加密，并设置短期 TTL。
- prompt、模型响应、审计日志和评估样本默认只保存脱敏版本。

## 11. 质量评估

离线评估指标：

- 意图识别准确率；
- 槽位抽取 F1；
- 指令完全匹配率；
- 有效指令率；
- 追问准确率；
- 追问后成功率；
- 人工审核召回率；
- 人工审核准确率；
- 误拒率；
- 模型版本 A/B 对比基准；
- 不安全自动执行率。

测试集至少覆盖：

- 高频正常请求；
- 中文口语化表达；
- 多意图请求；
- 缺字段请求；
- 相似术语混淆；
- 航司差异规则；
- 日期、航段、旅客序号边界；
- 高风险请求；
- 脱敏和回填；
- PNR 状态变化后的并发冲突。

不安全自动执行率是核心红线指标，目标应接近 0。

## 12. 实施计划

### Phase 1：PoC

- 整理 20 到 30 个高频 PNR 意图。
- 建立最小 PNR DSL。
- 接入 Bedrock `moonshotai.kimi-k2.5`。
- 建立 200 条标注测试集。
- 实现只预览、不执行的翻译 demo。

### Phase 2：受控试点

- 接入版本化术语表；如数据规模需要，再接入 OpenSearch/Knowledge Bases 检索。
- 增加规则校验、反解析和风险策略。
- 接入人工确认台。
- 扩展到 1000 条以上测试集。
- 对真实客服请求做旁路评估，不自动执行。

### Phase 3：生产上线

- 开放低风险白名单 intent 自动执行。
- 高风险指令保留人工审核。
- 建立每日回归测试。
- 建立失败样本回流和知识库版本管理。
- 建立模型版本升级评估流程。

## 13. 风险和应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 模型误解用户意图 | 生成错误中间表示 | 使用结构化输出、检索证据、低置信度追问 |
| 最终指令格式错误 | PNR 操作失败或误操作 | 使用 DSL renderer、反解析、语法校验 |
| 业务规则遗漏 | 执行不符合航司或内部规则 | 建立规则库版本管理和人工审核 |
| 敏感信息泄露 | 合规风险 | 模型输入脱敏、日志脱敏、KMS 加密 |
| 知识库过期 | 召回错误示例 | 文档版本、生效时间、废弃标识 |
| PNR 状态并发变化 | 执行上下文不一致 | 执行前重新加载状态并校验版本 |
| 成本不可控 | Bedrock 调用费用上升 | 低风险走主模型，复杂场景才调用 thinking 模型 |
| 客户端伪造执行人 | 越权执行 | 执行人和审核人只从认证上下文读取 |
| 模型输出非法 JSON | 后续链路异常或误解析 | schema 校验、有限重试、失败转人工 |
| 已执行动作无法回滚 | 业务损失 | 执行前校验、状态锁、补偿操作和人工恢复 |

## 14. 未决问题

- 目标生产区域是否已经启用 `moonshotai.kimi-k2.5` 和 `moonshot.kimi-k2-thinking`。
- PNR/GDS 指令规范的权威来源、版本和更新频率。
- 首批白名单 intent 由谁确认。
- 哪些操作允许自动执行，哪些必须人工确认。
- 现有 PNR/GDS 系统是否支持预校验、补偿操作和状态锁。
- 审计数据保留周期和合规要求。
- 租户、角色、审批链和 maker-checker 策略由哪个权限系统提供。

## 15. 结论

该系统可以采用 Bedrock 内置 Kimi 模型完成自然语言理解，但生产可控性的关键不在模型本身，而在结构化中间表示、确定性指令渲染、强校验、风险策略和人工兜底。
