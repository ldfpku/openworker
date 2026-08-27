# 治疗方案文档(Treatment-Plan Documentation)

## 硬性安全边界

本技能仅**格式化并结构化校验已经由授权的执业专业人员做出、提供并核实过的决策的文档记录**。

绝不要用它来:

- 诊断、评估、分类或筛查某个人;
- 选择、排序、推荐、替代或比较治疗方案;
- 选定药物、剂量、给药途径、频率、疗程或监测阈值;
- 开始、停止、暂停、恢复、滴定(titrate)、减量(taper)或停用任何治疗;
- 检查相互作用、过敏、禁忌症、脏器功能适用性，或治疗资格;
- 推断缺失的临床内容、间隔、日期、目标、升级标准或医嘱;
- 分诊(triage)、判断紧急程度、提供急诊建议，或制定安全计划;
- 预测结局、预后、疗效反应、获益、伤害，或临床适宜性;
- 替代用药重整(medication reconciliation)、药师审核、知情同意、临床医生审核，或授权的临床系统;
- 声称获得 FDA 批准、符合 HIPAA、符合法律法规、护理完整性、临床安全性，或符合诊疗标准。

如果某个请求越过了边界，应当停止。要求提供经本地核实的、由临床医生撰写的记录，或将该事项转交给负责的执业专业人员。不要为了获取针对具体患者的建议而把请求转到其他技能上。

如果某个问题可能是紧急或急重的，应停止本工作流程，并通过所在机构当前的临床升级或急诊流程处理该问题。本技能不判断紧急程度，也不提供急诊指导。

## 必须显示的提示

每个组件和推导出的日程表都必须显示:

> **草稿 —— 非医疗建议 —— 仅供文档记录 —— 需经授权临床医生签核**

结构校验通过绝不能移除这条提示。只有经授权的本地工作流程才可以设置发布关卡(release gate)。

## 数据准入关卡

优先使用合成数据或经合格审核的去标识化(de-identified)结构化清单。不要在示例中放入患者姓名、病历号、联系方式、出生日期、地址、自由文本备注、影像，或其他直接标识信息。

对于任何真实患者或源自患者的数据:

1. 仅在经本地授权的环境中、按照所在机构当前的隐私、安全、留存和访问政策开展工作。
2. 即使可能适用某项法律例外，也只使用达成既定文档目的所需的最少信息。
3. 不要将内容发送给模型、搜索引擎、API、图像服务、遥测服务，或任何其他外部工具。
4. 不要把内容复制进聊天提示、命令历史、日志、测试夹具(fixtures)、示例、截图或报告中。
5. 内置脚本只能对本地路径运行。它们的报告只标识规则代码和字段路径，不涉及临床数值。
6. 在将源自患者的材料视为已去标识化或对外发布之前，需要经过合格的隐私审查。

如果这些条件没有被记录在案，就不要读取或处理该内容。只使用合成模板。

## 允许的输入

只接受基于以下这些通用模板构建的、有边界限制的 UTF-8 JSON 对象:

- `assets/source_fact_manifest_template.json`
- `assets/clinician_authored_intervention_template.json`
- `assets/goals_monitoring_checkpoint_template.json`
- `assets/informed_preference_shared_decision_template.json`
- `assets/transition_reconciliation_template.json`
- `assets/intended_use_handoff_template.json`

这些模板不包含任何特定疾病的建议、示例患者、临床间隔、剂量、目标、阈值，或推断出的诊疗路径。空的模板数组和待处理的核证(attestation)状态是有意设置的发布阻断项。

## 工作流程

### 1. 确立权责与预期用途

- 确认负责的临床责任人和有权签署的签核人。
- 确认每一项临床决策都已存在于经核实的本地来源中。
- 记录管辖范围、机构、诊疗场所、文档所有者、本地政策、留存规则，以及预期接收方。
- 记录该资料包是合成数据、经合格审核的去标识化数据，还是最少必要范围内的真实患者数据。
- 在所有必需的审查完成之前，保持发布关卡处于 `blocked`(阻塞)状态。

在处理源自患者的材料之前，请阅读 `references/safety_scope.md` 和 `references/privacy_governance.md`。

### 2. 生成一个通用资料包

```bash
python3 scripts/generate_template.py \
  --output-dir ./local-plan-package \
  --subject-ref SYNTHETIC-CASE-001 \
  --classification synthetic
```

生成器会复制全部六个模板。它不会创建任何临床内容，也不会覆盖已存在的文件。

### 3. 逐字转录已提供的决策，不做任何推断

- 只从经核实的本地来源中复制由临床医生撰写的事实和干预措施。
- 保留来源定位信息、版本/日期、作者角色、核实角色，以及核实时间。
- 严格按照所提供的原样记录目标、监测项目、检查点日期，以及转诊/交接日期。
- 只按负责的临床医生所记录的内容记录选项、获益、伤害、不确定性、偏好和最终结果。
- 缺失的字段保持未解决状态。绝不用一般性知识去填补它们。
- 对于用药相关内容，记录临床医生撰写的文本和当前的本地来源引用；不要对其进行解读或验证。

参见 `references/documentation_workflow.md`、`references/source_boundaries.md` 和 `references/shared_decision_handoff.md`。

### 4. 运行确定性的本地检查

从本技能目录下:

```bash
python3 scripts/validate_treatment_plan.py ./local-plan-package
python3 scripts/validate_traceability.py ./local-plan-package
python3 scripts/check_completeness.py ./local-plan-package
python3 scripts/privacy_process_check.py ./local-plan-package
python3 scripts/check_consistency.py ./local-plan-package
python3 scripts/timeline_generator.py ./local-plan-package \
  --output ./local-plan-package/explicit-date-schedule.json
```

这些脚本会:

- 拒绝非本地路径、符号链接、重复的 JSON 键、未知字段、超大输入、过深嵌套，以及无边界限制的集合;
- 绝不使用网络访问、环境变量、动态执行、pickle、子进程、图像，或 LLM;
- 绝不评估诊断、用药安全性、相互作用、禁忌症、临床适宜性、紧急程度、预后，或指南符合性;
- 只对资料包中已提供的日期进行排程，绝不推导复发周期或临床间隔;
- 将报告内容压缩到最小，仅包含计数、规则代码、文档类型和字段路径。

### 5. 人工审查与发布

要求负责的授权团队:

- 将每一项转录内容与其已签署的来源逐一核对;
- 在经批准的系统中执行用药重整以及所有临床检查;
- 在适用时核实当前的 FDA 说明书、用药指南(Medication Guide)、REMS 材料，以及当地处方集/政策;
- 解决每一项差异和缺失项;
- 审查共同决策(shared-decision)和知情偏好文档;
- 审查交接接收方、责任归属、待定结果，以及本地升级路由;
- 在适用情况下完成隐私、安全、法律、监管、档案和机构审查;
- 通过授权的记录系统进行签署、注明日期并发布。

最终交接必须保留溯源信息以及未解决事项的路由方式。脚本检查通过并不等于授权将该资料包用于诊疗。

## 来源边界

- 只有在授权临床医生或药师核实其适用性之后，才可将 FDA 说明书数据库、当前用药指南和 REMS 材料作为权威来源记录使用。本技能不对它们进行解读。
- WHO 或 Joint Commission(联合委员会)的转诊/交接指南，仅用于流程结构方面，例如信息转移、重整文档记录、责任归属和检查清单。
- 使用 AHRQ、NICE 或适用的专业指南来记录"共同决策已经发生"这一事实；不要生成选项或风险估计。
- 只有在确认了具体的项目、提供者类型、管辖范围和当前本地政策之后，才可套用 CMS 的文档要求。
- 安全事件、产品报告、隐私事故及其他需上报事项，请通过当前的本地治理流程处理。本技能只负责记录路由，不负责提交报告。

带日期的官方来源清单参见 `references/source_ledger.md`。

## 验证

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s tests/treatment-plans -p 'test_*.py' -v
```

在不生成字节码的情况下运行 AST 解析:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -c \
  "import ast,pathlib; [ast.parse(p.read_text()) for p in pathlib.Path('scripts').glob('*.py')]"
```

## 参考资料索引

- `references/README.md` —— 范围与导航
- `references/safety_scope.md` —— 拒绝处理、路由转交与发布边界
- `references/privacy_governance.md` —— 本地处理与去标识化的限制
- `references/documentation_workflow.md` —— 资料包生命周期与审查关卡
- `references/source_boundaries.md` —— FDA 说明书、REMS 与治理边界
- `references/shared_decision_handoff.md` —— 知情偏好、重整与交接
- `references/source_ledger.md` —— 带日期的权威来源
- `references/security_validation.md` —— 基线发现与验证记录
