# 部署说明

## 前置条件

- AWS CLI 已配置目标账号和区域。
- 目标区域已在 Amazon Bedrock 中启用：
  - `moonshotai.kimi-k2.5`
  - `moonshot.kimi-k2-thinking`
- 本机已安装 Node.js 20+。
- 如首次在该账号/区域使用 CDK，需要先执行 `npx cdk bootstrap`。

## 本地验证

```bash
npm install
npm test
npm run build
npm run synth
```

## 部署

```bash
npm run deploy -- \
  --parameters PrimaryModelId=moonshotai.kimi-k2.5 \
  --parameters ReviewModelId=moonshot.kimi-k2-thinking \
  --parameters AutoExecutionEnabled=false
```

`AutoExecutionEnabled` 默认关闭。生产启用前必须完成白名单 intent、权限策略、maker-checker、人工审核和回归测试。

## API 示例

所有 `/v1/...` 路由都受 Cognito JWT authorizer 保护，需带 `authorization: Bearer <IdToken>`，且令牌用户已加入对应组。

翻译（需 `translator`/`executor`/`reviewer`/`admin`）：

```bash
curl -X POST "$API_URL/v1/pnr/translate" \
  -H "authorization: Bearer $ID_TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "session_id": "s-001",
    "pnr_context_id": "ctx-001",
    "user_text": "给第一个旅客第二段加一个东航素食餐",
    "pnr_context": {
      "passenger_refs": ["P1"],
      "segment_refs": ["S2"],
      "version": "v1"
    }
  }'
```

返回只包含脱敏指令预览 `command_preview_redacted`。真实可执行指令去脱敏后写入加密安全存储，由执行服务通过 `secure_command_ref` 在服务端读取，不从普通 API 返回。未提供 `pnr_context` 时不伪造旅客/航段，且该翻译不会被自动执行。

执行（需 `executor`/`admin`）。同一 `idempotency_key` 重放返回首次结果，不重复执行：

```bash
curl -X POST "$API_URL/v1/pnr/execute" \
  -H "authorization: Bearer $ID_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"translation_id": "tr-xxx", "idempotency_key": "idem-001", "pnr_context_version": "v1"}'
```

审核（需 `reviewer`/`admin`，且审核人不能是发起人）。高风险翻译 `manual_review` → `/approve` 后转 `ready_for_confirm` 才可执行：

```bash
curl -X POST "$API_URL/v1/pnr/reviews/rv-001/approve" \
  -H "authorization: Bearer $ID_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"translation_id": "tr-xxx", "review_note": "checked"}'
```

## 资源

CDK 会创建：

- HTTP API
- Cognito User Pool、User Pool Client 和基础角色组
- EC2 `t3.micro` Web 测试机，使用 nginx 托管静态页面
- Python Lambda
- DynamoDB 翻译表
- DynamoDB 执行表
- KMS key
- S3 加密短期指令存储 bucket
- Bedrock Kimi 模型调用权限

OpenSearch Serverless 不是默认必需资源。当前实现使用内置词典和可导入 JSON 术语表完成精确匹配；当术语、样例和历史数据规模扩大，并且需要向量召回时，再单独启用 OpenSearch 或 Bedrock Knowledge Bases。

## Web 测试页

部署完成后从 CDK 输出 `WebUrl` 获取页面地址，形如 `http://<web-instance-public-dns>`。

页面部署在单独的 EC2 小机器上，使用 nginx 托管。打开页面后：

1. 将 Cognito `IdToken` 粘贴到 JWT 输入框。
2. 点击 `Save`。
3. 选择 `Flight Sample` 或 `SSR Sample`。
4. 点击 `Translate`。
5. 如返回 `ready_for_confirm`，可点击 `Execute`。

## 认证和角色

所有 API 路由默认使用 Cognito JWT authorizer。部署后需要创建用户并加入对应组：

```bash
aws cognito-idp admin-create-user \
  --user-pool-id "$USER_POOL_ID" \
  --username operator@example.com \
  --user-attributes Name=email,Value=operator@example.com Name=email_verified,Value=true

aws cognito-idp admin-add-user-to-group \
  --user-pool-id "$USER_POOL_ID" \
  --username operator@example.com \
  --group-name translator
```

可用组包括 `translator`、`executor`、`reviewer`、`admin`、`auditor`。执行人和审核人从 JWT claims 解析，客户端请求体不能传 `confirmed_by` 或 `reviewed_by`。

## 可观测性

关键指标：

- 请求量、成功率、失败率；
- 平均延迟、P95 延迟；
- Bedrock 调用耗时和错误率；
- 检索命中率；
- schema 校验失败率；
- 业务规则校验失败率；
- 追问率；
- 人工审核率；
- 自动执行率；
- 执行失败率。

关键日志字段（每条翻译/执行记录必须包含）：

- `translation_id`
- `model_id`
- `prompt_template_version`
- `json_schema_version`
- `command_definition_version`
- `evidence_ids`
- `validation_result`
- `risk_decision`
- `execution_result`

## 部署方案

### 推荐拓扑

```text
CloudFront / WAF
  -> ALB
  -> AuthN / AuthZ
  -> ECS Fargate Service
  -> Bedrock Runtime
  -> S3 JSON Terms
  -> Optional OpenSearch Serverless
  -> DynamoDB
  -> S3
  -> Audit Store
  -> Human Review Console
  -> PNR/GDS Adapter
```

### 环境划分

- **dev**：开发调试，使用小规模样例库。
- **staging**：接近生产配置，接入脱敏后的真实样本。
- **prod**：生产环境，启用完整审计、告警和权限控制。

每个环境独立配置 Bedrock 模型访问权限、知识库索引、KMS key、审计存储和权限策略。

### 区域和模型可用性

生产部署前必须确认目标区域已经启用 `moonshotai.kimi-k2.5` 和 `moonshot.kimi-k2-thinking`。如果目标区域不可用：

1. 使用业务允许的可用区域部署模型调用链路；
2. 通过 Bedrock inference profile 或跨区域推理策略降低区域不可用风险；
3. 保持数据驻留、合规和网络延迟评估；
4. 不改走外部 Kimi API，避免破坏统一的 Bedrock 安全和审计边界。

### OpenSearch 取舍

OpenSearch 不是必需项，建议按阶段选择：

- **PoC**：内置词典或 S3 JSON 术语表即可，成本低、部署简单。
- **试点**：DynamoDB/S3 存储术语版本，应用内做精确匹配和别名匹配。
- **生产规模化**：启用 OpenSearch Serverless 或 Bedrock Knowledge Bases，承载向量检索、历史样例召回和 rerank。

当前 CDK 默认不部署 OpenSearch，避免为尚未接入主链路的 collection 产生固定成本。
