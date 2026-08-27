# Ontology Term Resolution(本体术语解析)

## 何时使用

任何时候，只要即将写下或信任一个本体标识符(ontology identifier):填写
元数据列、填写提交模板、审计他人产出的表格，或检查旧文件里的某个 ID 是否
仍然有效。

## 规则

**绝不要凭记忆写出一个本体 ID,也绝不要在不核实的情况下接受一个本体 ID**。

本体 ID 在形式上容易记住，但在细节上是任意的。一个看起来合理的
`UBERON:0002108` 是一个真实存在的术语(小肠),而不是肝脏，而且下游没有
任何环节能捕捉到这种替换错误——这个 ID 格式正确、本体也对，而元数据却
悄无声息地错了。审稿人同样发现不了这种问题，这正是这类错误会一路延续到
已发表数据集中的原因。

本技能给出的每一个 ID,都来自一次实时的 OLS 查询。经手的每一个 ID,都会
被核实。

## 两个方向

| 方向 | 脚本 | 回答的问题 |
| --- | --- | --- |
| 文本 → ID | `scripts/resolve_terms.py` | "left ventricle" 对应的术语是什么? |
| ID → 结论 | `scripts/validate_terms.py` | `EFO:0001067` 是真实存在的、是最新的，而且和文件中声称的标签一致吗? |

两者都可以接受单个值或文件，输出 TSV 或 JSON,除标准库之外不需要任何
第三方包。

## 把文本解析为术语

```bash
cd skills/ontology-term-resolution/scripts

# one string, constrained to the ontology that should define it
python3 resolve_terms.py "liver" --ontology uberon
```

```
query   rank  curie           label  ontology  match_type   strategy  defining_ontology
liver   1     UBERON:0002107  liver  uberon    exact_label  exact     true
```

```bash
# a column of tissue names; anything not an exact hit is reported, not guessed
python3 resolve_terms.py --input tissues.txt --ontology uberon \
    --exact-only --format tsv -o resolved.tsv

# accept fuzzy fallbacks, then review the partial hits by hand
python3 resolve_terms.py "left ventrical of heart" --ontology uberon --top 3
```

检索会依次升级:`exact`(标签和同义词)→ `token` → `fulltext`,一旦某种
策略返回了结果就停止，并报告是哪种策略命中的。`--exact-only` 会关闭这个
升级阶梯。`--branch UBERON:0000465` 会把候选结果限制在某个术语的后代
范围内。

**在使用某个结果之前，先看它的 `match_type`。** `exact_label` 和
`exact_synonym` 是安全的;`partial` 表示 OLS 针对一个字面上并不存在的
字符串，返回了它认为最接近的猜测，需要由人来做判断。`unresolved` 是一种
合理的输出——值得优先重试的规范化处理方式见
`references/curation-rules.md`。

## 校验既有的 ID

```bash
python3 validate_terms.py UBERON:0002107 EFO:0001067 UBERON:9999999
```

```
id              status     actual_label                  ontology  replacement     detail
UBERON:0002107  ok         liver                         uberon
EFO:0001067     obsolete   obsolete_parasitic infection  efo       MONDO:0005135   obsolete; replaced by MONDO:0005135
UBERON:9999999  not_found                                                          no such term in the ontology this prefix names
```

只要有任何一项失败，退出码就是 1,否则为 0,用法错误或网络故障时为
2——因此它可以作为元数据文件的 CI 关卡使用:

```bash
# id + label columns; catches IDs that exist but are labelled as something else
python3 validate_terms.py --input metadata.tsv --strict

# a tissue column must hold UBERON anatomical entities and nothing else
python3 validate_terms.py --input tissue_ids.tsv \
    --branch UBERON:0000465 --expect-ontology uberon
```

| 状态 | 含义 | 结论 |
| --- | --- | --- |
| `ok` | 存在、是最新的，且与所声称的一切都一致 | 通过 |
| `matched_synonym` | 所声称的标签是一个同义词；主标签与之不同 | 警告 |
| `imported_only` | 归属本体已不再认定这个 ID | 警告 |
| `not_a_class` | 该术语是一个属性(property)或实例(individual) | 警告 |
| `not_found` | 不存在这样的术语 | 失败 |
| `obsolete` | 已废弃；如果存在后继术语,`replacement` 会给出 | 失败 |
| `label_mismatch` | ID 与所声称的标签描述的是不同的事物 | 失败 |
| `wrong_ontology` | ID 类型正确，但对这一列来说本体不对 | 失败 |
| `wrong_branch` | 不是所要求的根节点的后代 | 失败 |
| `malformed_curie` | 不符合 `PREFIX:local` 的格式 | 失败 |

`--strict` 会把警告提升为失败。

## 会误导你的 API 行为

以下内容都是针对该在线服务实测验证过的，也是本技能提供脚本、而不是一份
操作说明的原因。完整细节见 `references/ols4-api.md`。

| 陷阱 | 后果 |
| --- | --- |
| `exact=true` 做的是精确的**词元**（token）匹配 | `liver` 在 UBERON 中返回 161 条命中；加上 `queryFields=label` 后只返回 1 条 |
| `/search` 从不返回 `is_obsolete` 或 `term_replaced_by` | 即便在 `fieldList` 中指定了这两个字段，它们也会被悄悄丢弃；只有术语详情接口才能回答"这个 ID 是否仍然是最新的" |
| `ontology=efo` 会返回 MONDO 和 CL 的命中结果 | 各本体之间会相互导入；需要自行按 CURIE 前缀过滤 |
| 同一个术语会在每个引入它的本体中各出现一次 | 应按 `obo_id` 去重，并保留 `is_defining_ontology: true` 的那一条 |
| `obo_id` 索引存在空洞 | `MONDO:0000001` 是有效的，但没有被 `obo_id` 索引收录；需要一个 IRI 回退方案，以避免出现错误的 `not_found` |
| 并非所有 IRI 都是 OBO PURL | EFO 和 Orphanet 使用各自独立的命名空间——应对 IRI 做实际解析，而不是套用模板拼出来 |
| OxO 已经停止服务 | 会以 HTTP 200 返回 HTML 页面；应改用术语交叉引用或 SSSOM |
| 分支(branch)检查并不会把细胞类型从解剖学范畴中排除出去 | CARO 把 `cell` 归在 `anatomical structure` 之下；还需要同时约束前缀 |

## 选择本体

疾病用 MONDO,表型用 HP,组织用 UBERON,细胞类型用 CL,检测/分析方法用
EFO,化合物用 ChEBI,物种用 NCBITaxon,性别和 `normal`(正常)用 PATO。
前缀到 OLS id 的映射关系(`HP` 在服务中对应 `hp`,`Orphanet` 对应
`ordo`)、`--branch` 所用的分支根节点，以及本体之间存在重叠时的判断
依据，都在 `references/ontology-registry.md` 中。

## 报告结果

要同时给出 ID **和**标签，并说明每一个是通过什么方式匹配到的。一张只有
裸 ID 的表格是无法被审阅的。对于未能解析的术语，要明确说明，而不要用最
接近的命中结果去填充。

## 参考文件

- `references/ols4-api.md` —— 端点、参数、响应字段，以及每一个经过验证
  的陷阱。
- `references/ontology-registry.md` —— 前缀/本体 id 对照表、分支根节点,
  以及各个概念分别归属哪个本体。
- `references/curation-rules.md` —— 候选项挑选流程、值得重试的规范化
  处理方式、如何审计一张既有表格、废弃术语，以及跨本体映射。
