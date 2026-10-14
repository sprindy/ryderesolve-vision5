# UI与Driver回应回合版：验收说明

## 实测结果

| 验证 | 实际结果 | 证据 |
|---|---|---|
| 完整Python回归 | **97项通过，0失败** | `docs/all-tests.txt` |
| 本轮参与方回合测试 | **14项**，包含在97项中 | `backend/tests/test_participation.py` |
| 实际HTTP服务 | uvicorn真实启动，FastAPI与编译LangGraph调用通过；虚拟时钟、8个场景、Driver有效补证后重评通过 | `docs/http-smoke-results.json` |
| 独立Demo基准 | **8/8场景通过**；标签不作为Agent输入 | `docs/demo-benchmark-results.json` |
| Chromium浏览器 | **8组交互通过**，无页面脚本错误 | `docs/browser-rounds-results.json` |
| 手机布局 | 390px下Admin总览与Driver回应页无横向溢出 | 同上及`docs/browser-rounds/`截图 |
| 前端语法 | 全部JS通过`node --check` | 实际命令验收 |
| 原件完整性 | 原DOCX与原始上传ZIP保持相同SHA-256 | 打包时生成`docs/input-integrity.json` |

## 本轮重点断言

Rider-only由后端签名身份实现，不只是隐藏按钮。Driver和Admin不能提交案件、发起官方样本，或通过`actor=rider`冒用提交；Rider不能替Driver回答，非当前回合不能写入回应。跨工作区、陈旧邀请、重复的不同回应与错误附件引用均受控。

缺证据案件实际停在`awaiting_response`，不在后台偷偷把后续回合跑完。Driver同意作为让步协议记录，不改写Agent的初步责任事实，不进入责任先例。并发重复同意只产生一条回应、一条Mock退款效果。后续安全标记或hash篡改不能被同意绕过。

Driver拒绝须有理由，可无附件。理由通过只读工具进入两个Advocate与Judge评估上下文；普通文字和未核验JSON不是行程事实。无服务器佐证时转人工；通过既有来源manifest核验的四分钟等待补证会被三Agent重新评估并确认维持收费。旧评估快照、回应和工具活动可追溯。

模拟12小时直接推进时钟。弱证据Driver回合未回应只转人工；不会推断Driver同意。充分证据的已有决定复核顺序Driver→Rider，接受和挑战按当前角色受控，到期依验证决定结案而非伪造双方接受。

## 浏览器实际覆盖

测试从空工作区Admin开始，确认第一版总览且没有提交按钮；随后在Rider真实提交，并切换Driver页面执行同意、无佐证拒绝和核验补证拒绝三条路线。测试还点击总览案件导航、Response rounds、人审引用提交，并检查390px手机页面。截图为真实浏览器渲染，不是UI静态示意。

## 不代表已经完成的部分

测试默认`deterministic`，没有本轮真实付费LLM请求、真实通知、真实支付、真实Ryde证据认证或生产用户身份。97项回归和8个合成场景不代表模型真实准确率、100条独立标注、概率校准或法律裁决有效性。

仍采用单进程SQLite和临时预览；未强制增加完整checkpointer、多worker、OCR、向量检索或无限协商。原因见`docs/UI_AND_RESPONSE_ROUNDS.md`与`docs/IMPLEMENTATION_SCOPE.md`。最终源码包排除密钥、已运行数据库、会话凭证、缓存和一次性开发补丁脚本。

## 下载包干净解压验证

最终ZIP解压到独立新目录后，执行 `python backend/smoke_test.py`：实际uvicorn/HTTP验收通过，11项检查包含8个场景、虚拟时钟和Driver补证后Agent重评。随后由种子建立全新默认数据库，案件数为0，证明下载包不依赖已运行案件或旧数据库。记录见 `docs/release-package-smoke.json`。

## 2.1凭证恢复修复

旧缓存通过只读签名接口验证，失效后建立一次新隔离工作区，有效身份保留。新增4项Python与6项JS回归、真实浏览器旧缓存恢复通过；验证Rider提交和Driver回应可用。写操作不自动重放、403不自动换身份。完整说明见`DEMO_CREDENTIAL_FIX.md`。
