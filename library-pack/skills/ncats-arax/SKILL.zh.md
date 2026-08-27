# NCATS ARAX

把 ARAX 当作一个受限的知识图谱查询服务来使用。提交经过审查的 CURIE 和明确的 Biolink 类型，保持 TRAPI 交换内容原样不变，检查查询边(query-edge)的绑定关系与来源信息(provenance),并把每一条返回的路径都当作有待后续验证的候选结果来对待。

在构造查询之前，先阅读 [query-contract.md](references/query-contract.md)。在解读已保存的产物、警告、来源信息或部分结果时，阅读 [output-schema.md](references/output-schema.md)。

## 安全边界

- 只使用公开的、非敏感的研究问题。即便请求了 `store=false`,ARAX 的状态设施仍可能暴露查询内容和调用方的元数据。
- 不要提交患者信息、机密研究问题、未发表的化合物研发计划，或专有的靶点假说。
- 不要把返回的某条路径当作已验证的机制或临床建议来呈现。
- 把结果为零报告为"在这些约束条件下未返回结果",而绝不能说成是"不存在该关系"的证据。
- 应把结果的位置描述为未经评分的响应顺序，而绝不能称之为排名。
- 对重要的候选结果，应另外通过文献和权威数据库进行核实。

## 工作流程

1. 单独对自由文本进行归一化(normalize),然后审查并报告所提议的 CURIE 和类别(category)。
2. 选择一个带类型的单跳查询，或一个两端都已固定的严格两跳查询。
3. 除非用户明确指定了两到五个提供方(provider),否则使用默认的 RTX-KG2 查询方式。
4. 确认该生物医学查询是公开的，并选择一个新建的或空的输出目录。
5. 只运行一次客户端。在出现失败或空结果之后，不要悄悄改变提供方选择或展开顺序。
6. 检查 `summary.json` 中的受限绑定关系和来源信息，以及 `response.json` 中确切的 TRAPI 载荷。
7. 在 ARAX 之外，对科学上重要的路径进行核实。

## 预检（Preflight）

在不发起生物医学查询的情况下，检查生产环境的 OpenAPI：

```bash
python skills/ncats-arax/scripts/arax_client.py preflight
```

该客户端会验证该服务是否自我标识为 ARAX、是否暴露了 `/query` 接口，以及是否报告了受支持的 TRAPI 版本。若目标是非生产环境端点或未经测试的 TRAPI 系列版本，需要显式覆盖参数；这两种覆盖都不会改变固定的查询形态或操作方式。

## 归一化一个实体

归一化只用于审查，绝不会触发图查询：

```bash
python skills/ncats-arax/scripts/arax_client.py normalize "primary myelofibrosis" \
  --expected-category biolink:Disease \
  --max-synonyms 10 \
  --acknowledge-public-query \
  --output-dir outputs/normalize-myelofibrosis
```

在使用某个 CURIE 之前，先审查其规范标识符(canonical identifier)、名称、类别以及同义词预览。无论查询结果如何，都应报告全部 CURIE 和类别。类别警告或零结果是需要去精心核实该标识符的理由，而不是自动串联到 `/query` 的理由。

## 单跳查询

至少固定一端节点，并为两个节点都指定类型：

```bash
python skills/ncats-arax/scripts/arax_client.py one-hop \
  --subject-id CHEBI:31690 \
  --subject-category biolink:SmallMolecule \
  --predicate biolink:affects \
  --object-id NCBIGene:25 \
  --object-category biolink:Gene \
  --qualifier biolink:object_aspect_qualifier=activity_or_abundance \
  --qualifier biolink:object_direction_qualifier=decreased \
  --acknowledge-public-query \
  --output-dir outputs/imatinib-abl1
```

查询(lookup)模式是默认模式，其展开范围固定为 `infores:rtx-kg2`。它默认返回 20 条结果。使用 `--result-limit N` 可请求 1 到 50 条结果；无论哪种模式,50 都是硬性上限。

## 端点固定的两跳查询

只能使用一个带类型、未固定的中间节点：

```bash
python skills/ncats-arax/scripts/arax_client.py two-hop \
  --subject-id CHEBI:66901 \
  --subject-category biolink:SmallMolecule \
  --predicate-1 biolink:affects \
  --intermediate-category biolink:Gene \
  --predicate-2 biolink:associated_with \
  --object-id MONDO:0009061 \
  --object-category biolink:Disease \
  --qualifier-1 biolink:object_aspect_qualifier=activity_or_abundance \
  --qualifier-1 biolink:object_direction_qualifier=increased \
  --expand-order right-first \
  --acknowledge-public-query \
  --output-dir outputs/ivacaftor-cystic-fibrosis
```

从右侧优先展开(right-first)是默认方式。如果空结果值得再次尝试，应显式地用 `--expand-order left-first` 运行一次新查询，并让两次运行的结果保持独立分开。

## 指定提供方的联合查询

联合查询(federation)是显式的，接受两到五个具名的提供方：

```bash
python skills/ncats-arax/scripts/arax_client.py one-hop \
  --subject-id CHEBI:31690 \
  --subject-category biolink:SmallMolecule \
  --predicate biolink:affects \
  --object-id NCBIGene:25 \
  --object-category biolink:Gene \
  --mode federated \
  --kp infores:rtx-kg2 \
  --kp infores:molepro \
  --acknowledge-public-query \
  --output-dir outputs/federated-imatinib-abl1
```

联合查询默认使用 50 条结果的硬性上限。提供方错误可能与有用的结果同时出现；这样的一次运行会在保留其产物之后以退出码 7 结束，并被标记为部分完成(partial)。

## 检查已保存的来源信息

在不联网的情况下重建一份受限摘要：

```bash
python skills/ncats-arax/scripts/arax_client.py summarize \
  --request outputs/ivacaftor-cystic-fibrosis/request.json \
  --response outputs/ivacaftor-cystic-fibrosis/response.json \
  --format text
```

该检查工具只接受与实时命令所生成的相同的受限请求形态和固定操作。使用 `--format json` 可在标准输出上获得归一化后的视图。

## 解读结果

- 应跟随每次分析的查询边绑定关系；不要对知识图谱中的每一条边都做汇总。
- 保留 ARAX 返回的实际边的主语(subject)、谓词(predicate)、宾语(object)及限定符(qualifier)取值。返回的谓词或限定符方面(qualifier aspect)可能比查询约束更为具体。
- 检查所有的来源(source)对象，包括主要来源、聚合方、支撑数据、上游资源以及来源记录 URL 字段。
- 应把 `publication_availability: not_returned` 理解为元数据缺失，而不是不存在相关出版物的证据。
- 应把缺失的辅助图引用(auxiliary-graph reference)和提供方失败，视为明确的警告信息。
- 每当受限摘要遗漏了细节，或该服务的响应结果是部分的、不熟悉的、或在科学上出乎意料时，都应查阅原始响应。

## 有意排除的功能

该客户端不具备原始查询(raw-query)、工作流(workflow)、操作(operation)、叠加(overlay)、排名(ranking)、推理(inference)、链接预测(link-prediction)、Pathfinder、ARS、批处理(batch)、全提供方(all-provider)、三跳(three-hop)、缓存(cache)、守护进程(daemon)、SDK、MCP,或自然语言转 TRAPI 的接口。不要在此技能之下，通过直接的 HTTP 调用来绕开这些限制。

## 官方参考资料

- [ARAX 文档](https://ncatstranslator.github.io/TranslatorTechnicalDocumentation/architecture/ara/arax/)
- [ARAX 生产环境 OpenAPI](https://arax.transltr.io/api/arax/v1.4/openapi.json)
- [ARAXi 操作文档](https://github.com/RTXteam/RTX/blob/master/code/ARAX/Documentation/DSL_Documentation.md)
- [Translator Reasoner API](https://github.com/NCATSTranslator/ReasonerAPI)
- [Biolink Model](https://biolink.github.io/biolink-model/)
