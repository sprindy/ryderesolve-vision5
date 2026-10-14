# 当前展开修复与历史记录修订：验证

54项组件／协议回归通过；最后一次区分 total_trips 与 completed_trips 的字段语义修订后，6项历史定向复核通过。另有6项凭证恢复前端测试通过，以及12项Headless Edge回归检查通过。定向复核与原组件测试有重叠，不作为额外独立案例数。Python与JS语法检查通过。

- 当前代码的 SQLite、只读工具、Agent 类、Validator、confidence/refund 和 workflow 节点组件测试见 history-component-results.json。运行器只为导入领域代码替换 HTTPException 类型；没有模拟 FastAPI 应用或 LangGraph 来声称集成通过。
- 新测试覆盖双方官方嵌套历史、Driver/Rider outcome 语义、Unknown、最小化字段、部分历史中性混合、同工作区更早不同旅程、重复行程去重、只读限制、历史不能改变本案 liability 和双方实际工具调用。
- Headless Edge 浏览器：多轮自动刷新保持展开；手动关闭保持关闭；嵌套 Evidence；分页返回；不同Case隔离；Driver回应历史；Policy和Evaluation子页面不被轮询替换；双方历史显示；手机无横向溢出。浏览器使用实际数据库／Agent／节点组件输出拦截API，不能替代真实服务测试。
- 官方数据文件与政策文件没有修改，见 history-input-integrity.json；没有新增官方历史、历史先例或真实业务资料。

## 尚未验证

当前 http-smoke-results.json 为 passed=false / blocked：本次可访问Python缺 langgraph、fastapi、uvicorn、dotenv，依赖下载因网络限制失败。这不意味着用户已安装的环境没有依赖。旧版本通过报告已移到 previous-release-validation。

使用本地已安装环境，在项目根目录执行：

```powershell
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

完整回归：`cd backend` 后 `python smoke_test.py` 与 `python -m unittest discover -s tests`。只有新报告 passed=true 才确认本版本完整API／编译图执行成功。真实LLM联调仍需本地 .env 配置与实际调用。

可复现浏览器fixtures回归：安装Node的playwright包后运行 `node scripts/browser_history_details.cjs`（Windows Edge）。该脚本拦截API，不访问真实服务；原真实服务浏览器脚本另保留。
