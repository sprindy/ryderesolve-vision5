# UI对齐与参与方回应回合（第2版）

## 本轮依据

用户要求对齐第一版UI；只有Rider可以提交dispute；证据或confidence不足时，先询问Driver是否同意Rider的诉求。用户进一步明确：例如同意撤销取消费；不同意则提交理由或证据，交给Agent评估；仍无法确认则转接人工。

本轮保留FastAPI、Python Agent、LangGraph和SQLite，不迁移到另一套前后端。原始Ryde Vision 5 DOCX、原上传源码ZIP及上一版修正版均不覆盖。这里的“回合”是**参与方实际回应阶段**，不是把Agent循环执行伪装成用户轮流操作。

## 用户确认的流程

| 阶段 | 当前操作方 | 实际行为 | 后续 |
|---|---|---|---|
| 1. 提交 | Rider | 选择Demo行程并提交不可变投诉。Driver和Admin都不能代替发起 | 三Agent初步评估 |
| 2. 证据/置信度不足 | Driver | 明确询问是否同意Rider的撤销收费诉求；页面和后端都暂停等待 | 同意或不同意 |
| 2a. 同意 | Driver | 签名身份下明确同意诉求 | 合法且有可核验金额来源时，按**当事方协议/Driver让步**结案，非Agent责任证明 |
| 2b. 不同意 | Driver | 必须填写理由，可上传可选JSON材料 | 两个Advocate与Judge重新评估；不自动再次轮到Rider争辩 |
| 3a. 能确认 | Agent与确定性引擎 | 来源验证、政策适用、置信度和资金计算守卫通过 | 记录Agent结论并Mock结算 |
| 3b. 无法确认 | 人工Reviewer | 明确显示未解决原因、Driver回应和证据 | 引用式人工审核 |
| Driver未回应 | Admin模拟时间 | 一键推进逻辑12小时 | 转人工，绝不把沉默当同意 |

**Driver回应的是Rider的诉求，不是系统初步建议。** Driver文字和未核验上传只是陈述，不会改变GPS或收费事实。有效的Demo服务端导出经过原有trip-scoped manifest验证，才可作为可信补证。反对理由也通过只读证据工具进入Agent上下文并留下审计记录。

安全威胁、来源完整性失败、政策歧义、模型/契约失败等硬阻断继续直接转人工；不靠Driver同意绕过这些保护。缺少定价依据或没有支持的补偿公式时，即使Driver同意也不捏造金额。

## 原有高充分性流程如何处理

已有充足证据的初步决定仍保留上一版的模拟挑战权，并限制响应顺序为**Driver先回应，随后Rider回应**。这条分支是在评估已明确的系统决定，和“不足证据下询问Driver是否同意Rider诉求”分支在UI、状态、来源和审计中分开。

高充分性案件模拟到期可依已验证决定终结，来源明确写为`expired_without_material_challenge`，**不是双方同意**。弱证据的Driver回应回合到期则必须转人工。两个分支都无需真实等待12小时。

## UI对齐

沿用第一版Ryde红白品牌、240px侧栏、浅灰工作区、白色卡片和小红色主按钮，恢复「Every dispute. A fairer outcome.」总览、四张真实统计卡、三Agent示意、待办与案件表。没有静态假数字。证据、政策、Agent活动和审计保留在案件详情标签中，技术性置信度细项默认收起。

Admin没有Submit按钮；Driver没有Submit按钮。只有Rider页面有提交入口，接口也要求签名Rider身份及`actor=rider`。样本启动同样限制Rider，避免Admin从另一入口发起案件。Admin可查看、模拟时钟和审核，但不可回答Driver的回应请求。

回合面板显示“谁该回应”、明确同意对象、Driver理由/材料、响应历史和最终去向。切换Demo角色仍只是在同一隔离工作区内的演示体验，不宣称生产级登录/RBAC。

## 技术实现索引

| 文件 | 本轮变化 |
|---|---|
| `backend/app/main.py` | Rider-only发起；Driver回应接口；回应阶段上传权限；模拟时间与审计投影 |
| `backend/app/participation.py` | 邀请、Driver回应、请求幂等、协议权限检查、转人工与回应超时 |
| `backend/app/workflow.py` | 不足证据实际暂停；Driver拒绝后重新运行三Agent；不确认时转人工 |
| `backend/app/settlement.py` | 协议和Agent结论来源分开；原子幂等Mock结算；顺序式充分性复核 |
| `backend/app/evidence_intake.py` / `*_agent.py` | Driver陈述作为不可信材料进入工具和Agent上下文；可信补证仍需来源验证 |
| `frontend/admin-dashboard.js` | 第一版信息层级与真实工作区总览 |
| `frontend/party-turns.js` | 当前角色动作、回应表单、材料上传与回合历史 |
| `frontend/workspace-v2.css` | 第一版视觉对齐及桌面/手机回合样式 |
| `backend/tests/test_participation.py` | 新业务的真实API回归，而非仅页面隐藏 |

## 有意未扩展及原因

本轮不再实现无限Rider/Driver交替谈判、任意协商金额或多方仲裁，因为用户已明确Driver反对后由Agent评估，不确定就转人工；加入这些会改变业务含义。Demo只覆盖已有JSON补证链路，图片/PDF/OCR需要独立来源校验和业务规则，不把任意文件当事实。

默认离线确定性Agent，保留原LLM接口但本轮不发真实付费模型请求，也不宣称验证真实自然语言推理质量。其他上一版的真实通知、支付、生产身份、多worker持久恢复、向量检索、概率校准和大规模真实评测差距仍存在，原因保留在`IMPLEMENTATION_SCOPE.md`。本轮只是新增用户确认的流程和UI，未伪造这些外部能力。
