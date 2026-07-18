# PNR 翻译助手（自然语言 → PNR 机器指令）

基于 Amazon Bedrock 内置 Kimi 模型的自然语言到 PNR 机器指令翻译系统。核心思路：**模型只做语义理解和结构化中间表示，最终指令由确定性 DSL renderer 生成，并经过 schema / 语法 / 业务 / 权限 / 风险多层校验**；高风险与低置信度请求进入澄清或人工审核。

> 源自 AWS 博客[《使用大模型构建自然语言到 PNR 机器指令翻译系统》](https://aws.amazon.com/cn/blogs/china/building-a-natural-language-to-pnr-machine-instruction-translation-system-with-deepseek/)的工程化改进版。完整设计、评审结论与取舍见 [docs/architecture.md](docs/architecture.md)。

## 核心设计

- **Bedrock 唯一大模型入口**：主链路 `moonshotai.kimi-k2.5`，复杂复核 `moonshot.kimi-k2-thinking`，不接外部 API。
- **模型不直接出指令**：模型输出 JSON 中间表示，由 `PNR Command Renderer` 按 DSL schema 渲染最终指令，并反解析校验一致性。
- **风险分级**：低风险白名单可自动执行；中风险需用户确认；高风险 / 低置信度 / 多意图转人工审核，且强制 maker-checker（审核人 ≠ 发起人）。
- **全程脱敏**：模型输入与普通日志只见占位符；真实可执行指令去脱敏后写入加密短期存储，不在 API 响应中返回。

## 实现状态与边界

本仓库是**设计评审 + 可运行原型**，核心链路（脱敏 → 检索 → 模型中间表示 → DSL 校验/渲染/反解析 → 风险分级 → 脱敏预览/真实指令安全存储 → maker-checker 审核 → 幂等执行记录）均已实现并有单元测试覆盖。以下为占位实现，接入生产前需替换：

- **PNR/GDS 执行**：`execute` 校验权限、状态版本、幂等键后只写执行记录，**未真正调用 GDS**。生产需接入真实 Adapter 并实现执行前状态锁与补偿。
- **检索**：内置术语词典 + 可导入 JSON 术语表的精确匹配；向量召回 / 历史样例 / rerank 未启用。
- **模型调用**：Bedrock 不可用时走确定性兜底，仅便于本地测试与未开通模型访问时演示，不代表生产质量。
- **多租户与权限**：角色从 JWT claims 解析，无 claims 即拒绝；真实租户 / 审批链需对接企业权限系统。

## 文档

- [docs/architecture.md](docs/architecture.md)：架构图、核心模块、API、数据模型、安全、实施计划与风险。
- [docs/deployment.md](docs/deployment.md)：部署、接口调用、可观测性与部署方案。
- [docs/testing.md](docs/testing.md)：测试用例与验证方法。

## 快速开始

```bash
npm install
npm test        # Python 单元测试
npm run build   # 编译 CDK (TypeScript)
npm run synth   # 生成 CloudFormation 模板

npm run deploy -- \
  --parameters PrimaryModelId=moonshotai.kimi-k2.5 \
  --parameters ReviewModelId=moonshot.kimi-k2-thinking \
  --parameters AutoExecutionEnabled=false
```

`AutoExecutionEnabled` 默认关闭。部署前请确认目标区域已开通上述 Bedrock 模型，详见 [docs/deployment.md](docs/deployment.md)。

## 目录结构

```
src/pnr_service/   Python Lambda：脱敏 / 检索 / 模型适配 / DSL / 风险 / 存储 / 编排
infra/             CDK：API Gateway + Cognito + Lambda + DynamoDB + KMS + S3
web/               静态测试页（nginx 托管）
tests/             单元测试
docs/              设计、部署、测试文档
```

## License

MIT - see the [LICENSE](LICENSE) file for details.

## 免责声明

- 本项目仅供学习与技术参考，是设计评审与可运行原型，不构成生产部署方案。
- 运行过程中会创建 AWS 资源并调用 Amazon Bedrock 模型，产生费用，请在实验结束后及时清理。
- 作者不对因使用本项目产生的任何费用或损失承担责任。
- 本项目与 Amazon Web Services 及 Moonshot AI 无官方关联，相关服务的可用性与定价以各方官方文档为准。
- PNR/GDS 指令、航司规则等为脱敏示例，不代表真实业务规范。
- 生产环境使用前请根据实际需求进行安全评估与调整。
