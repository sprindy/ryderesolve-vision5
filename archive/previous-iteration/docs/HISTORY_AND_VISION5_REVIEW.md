# 本次修复与 Vision 5 实现核对

核对对象：用户提供的 **Ryde_Vision5_Demo_UI与回应回合版_凭证修复.zip**，不是先前的旧版 ZIP。依据：Ryde_Technical_Design_Document_Vision_5.docx。结论：已有完整演示骨架，但仍不是全部 Vision 5／生产要求都已实现。

## 本次修复

1. **详情展开自动关闭**：两秒轮询会重建 HTML，原来没有保存 details.open。本次按工作区、角色、Case ID、分页保存每个详情的展开和关闭状态，支持嵌套证据详情、强制刷新、切换分页后返回；不同案件不串状态。另修复 Policy & precedents / Evaluation lab 被后台轮询覆盖回案件页面的问题。页面重载后默认重置展开状态，这是页面内阅读状态，不写入业务数据库。
2. **双方历史记录**：原包只有 Rider 扁平历史字段的原型，官方嵌套 dispute_history 没有正确匹配，而且没有 Driver 历史工具。本次新增 get_party_history（rider/driver/both）和 get_pairwise_history，作用域从当前案件确定，不能传任意 party_id 访问他人。
3. 两个 Advocate 的离线与真实 LLM 路径都查询双方历史和 pairwise 记录；真实模式未完成这些查询不能直接提交最终论点。Judge 接收相同历史背景；历史不进入决定当前责任的 liability_rule。
4. Admin、Rider、Driver 新增 **Party history**，显示已知计数、Unknown、来源、双方结果语义、历史评分计算及成对历史范围。Agent activity 和 audit 保留查询及考虑历史的事件。

## 历史数据来自哪里

| 官方 DISP-002 已提供字段 | Rider | Driver |
|---|---:|---:|
| 账号年龄（天） | 210 | 900 |
| 行程总数 | 34 | 3201 |
| 既往争议／投诉总数 | 4 | 1 |
| Rider 争议 upheld | 1 | 不适用／未知 |
| 投诉 upheld against Driver | 不适用／未知 | 0 |
| rejected | 3 | 1 |
| 平均评分（仅作背景） | 3.9 | 4.9 |
| 已记录 flag 数（不是当前责任证明） | 1 | 0 |

同类争议次数、inconclusive、异常退款次数以及双方此前共同乘车明细，原样本没有提供，因此 **Unknown**，不补为0、不生成历史案例。原始官方文件和政策文件的 SHA-256 与上传 ZIP 内容相同。

SIM-HIST-001 原有的合成 Rider 计数继续明确标为 Synthetic demo；没有将它伪装成官方历史。Pairwise 工具只查询同工作区、已终结、时间更早、不同于当前行程的记录，并按 trip ID 去重。没有记录不证明双方在平台上从未乘车。

原样本 total_trips 不被重命名成已完成行程；completed_trips 未明确提供时仍为Unknown。年龄与评分显示为背景，当前数字公式并非文档要求的完整校准历史模型。

历史规则：资料完整时使用原型结构化频率公式；仅有部分官方计数时，已观察频率得分与中性0.5各占50%，缺失字段仍为Unknown；计数不足时使用0.5。Rider 的 rejected 与 Driver 的 upheld_against 分别解释，不能互换。双方分数平均后仅影响信心公式中 **10% claim reliability**，也可要求更强佐证。平均评分、flag 数不直接惩罚责任；历史不能推翻本案GPS冲突、缺失证据，也不能授权退款。这是可解释工程原型，不是校准概率或欺诈模型。

## 对照文档：仍未完成／只有演示替代的项目

| 项目 | 当前状态与仍缺部分 |
|---|---|
| 双 Advocate 并行 fan-out / fan-in | **未实现**。实际 LangGraph 节点仍串行，第一轮上下文独立，后续读取上一完整轮。 |
| LangGraph checkpoint 持久化与中断续跑 | **未完整实现**。有节点快照和审计，重启对未完成案件转人工；没有 checkpointer pause/resume、自动恢复及分布式工作队列。 |
| 引用型强类型 graph state | **未完整实现**。主要仍是 TypedDict payload + JSON bundle，而非文档要求的小型强类型状态和外部证据引用。 |
| 真实历史政策生效日期与条件匹配 | **仅 Demo 替代**。已有版本筛选、固定 policy refs、priority/exception/specificity 基础选择；日期明确是合成演示日期。真实 event-time 生效日期、地域／service 条件与权威来源未知时仍需人工，不能声称全部接入。 |
| 平台 Rider／Driver 历史服务 | **本次补齐样本／演示路径，生产未接入**。真实平台历史接口、历史更新时间和完整事件明细仍不可用；缺失不虚构。 |
| 平台 pairwise 历史 | **本次补齐只读工具，真实数据库未提供**。只查本工作区实际终结的更早不同旅程，平台整体历史Unknown。 |
| 先例语义 embedding / pgvector | **未实现**。已有工作区内合格终局先例、固定政策过滤、结构化特征排序和偏离检查；不是语义向量检索，也不是全平台先例库。 |
| 历史先例审理权威、撤销与治理 | **部分**。已有可验证人审反馈及 eligibility；没有完整权威层级、撤销传播、平台审批和学习治理。 |
| 真实 traffic / road closure adapter | **未接入**。模拟导航记录有ETA／路线；没有独立实时交通或封路服务。 |
| 通用 pricing/refund 规则 | **部分**。支持原取消费撤销及固定报价超额，整数cents与审计／幂等效果；没有完整 surge、税费、优惠、分项fare和通用路线补偿。无授权公式时阻断，不能虚构赔偿。 |
| 真实通知与付款 | **未接入**。通知和退款效果为 Mock，时钟为 Demo 虚拟时间，不是真实成功投递或实际资金执行。 |
| 真实用户／员工身份与细粒度权限 | **仅 Demo 替代**。签名工作区凭证和角色检查已存在，凭证修复保留；不是真实 party_id 登录、员工RBAC和列级资料权限。 |
| 完整来源认证、PII/DLP与留存策略 | **部分**。有元数据、hash、父引用、最小化profile及可见范围；模拟来源hash不是业务签名，聊天／上传内容未接完整PII识别和生产数据留存。 |
| 任意自然语言事实／政策 Validator | **部分**。有typed schema、IDs、hash、有限业务事实和裁定语义守卫；不是任意自然语言论证的证明器。 |
| 生产 safety classification | **未接入**。目前是保守关键词路由原型，不是完整多语言分类器。 |
| PostgreSQL／正式 Repository／多worker CAS | **未实现**。SQLite单进程、事务与幂等键；没有完整分布式部署与外部支付 exactly-once。 |
| 100独立案例、ablation、校准及真实LLM评测 | **未完成**。保留原八场景演示基准；没有100个独立专家标注、模型多seed、概率校准、消融和实际模型准确率证据。 |
| 生产 observability | **部分**。本地节点耗时、工具和provider审计已存在；没有完整OpenTelemetry、长期监测、业务准确率标签及真实成本评测。 |
| 真实 provider 端到端联调 | **可配置，仍未由本次验证**。Responses／compatible Chat Completions 适配器在包内；未配置真实模型密钥。 |

已有核心功能：三个独立角色、实际 LangGraph 图实现、只读工具、material gate、最多三轮辩论、五因子工程信心分、deterministic金额、人工原因、Driver回应回合、审计与UI。它们的存在不能代替本次完整服务运行验证。

## 本次验证边界

见 docs/history-component-results.json、docs/history-browser-results.json、docs/http-smoke-results.json。组件测试与真实浏览器fixtures验证当前改动；完整FastAPI／编译LangGraph smoke本次受可访问Python缺少依赖及网络限制而blocked。上传包原有的通过报告移入 previous-release-validation，仅作为旧版本资料，不能当作本次通过证据。
