# 病原体变异株监测（Pathogen Variant Surveillance）

## 何时使用

只要答案依赖于病原体种群**当下**的状态——哪些谱系正在流行、某个谱系是否正在增长、某个谱系名称当前指代什么，或者某个检测靶点是否仍然匹配——就应使用此技能。

## 规则

**永远不要凭记忆陈述当前流行情况，也永远不要凭记忆写出谱系名称**。

有三件事会同时出错，而其中只有第一件是普通的"知识截止日期"问题：

1. **名称在训练数据截止之后出现**。 Pango 命名列表已包含超过 6,200 个名称，且在持续增长。
2. **该命名体系是一个实时数据结构，而不是一种命名惯例**。 `XFG` 是一个重组株，只能通过 `alias_key.json` 才能解析出来;`PQ.17` 展开后是 `XDV.1.5.1.1.8.1.17`。这两种展开都无法靠推理得出——这套映射关系是一份会不断变化的文件。
3. **既有知识不仅会过时，还会被撤回**。 当前 `lineage_notes.txt` 中有 294 个名称已被撤销或重新指定。`PC.2` 现已改名为 `LF.7.9`;`XFG.20` 则被彻底撤销。凭记忆得出的谱系信息不只是"陈旧",它可能是彻头彻尾错误的。

此技能报告的每一个数字，都是来自某个实时实例的计数结果，并标注了其所来自的数据版本。

## 适用范围

面向研究用途的监测数据分析。此技能描述的是已被采集并提交的序列；它不产出临床解读、疫情应对建议或公共卫生指导，序列计数也不等于病例计数。

## 实例（Instances）

一套 API 结构覆盖所有病原体。`--instance` 指定一个已验证的部署;`--base-url` 可访问任何其他 LAPIS 实例。

| 实例 | 主机 | 谱系字段 | 是否建有索引 |
| --- | --- | --- | --- |
| `sars-cov-2` | lapis.cov-spectrum.org(开放的 GenBank 数据) | `pangoLineage` | 是 |
| `h5n1`、`h3n2`、`h1n1pdm`、`influenza-a` | lapis.genspectrum.org | `clade` | 否 |
| `rsv-a`、`rsv-b`、`mpox`、`measles`、`dengue`、`west-nile`、`hmpv`、`ebola-zaire`、`ebola-sudan`、`cchf` | lapis.pathoplexus.org | 因实例而异 | 因实例而异 |

**字段名称因实例而异，不应做任何假设**。 每个脚本都会在运行时读取 `/sample/databaseConfig`,并根据该实例实际声明的内容选取采集日期、提交日期和谱系字段列。`dateFrom=` 在 SARS-CoV-2 上是合法的，但在 H5N1 上会直接返回 400 错误——H5N1 的采集日期字段是 `sampleCollectionDateRangeLower`。

## 脚本

```bash
cd skills/pathogen-variant-surveillance/scripts
```

| 脚本 | 回答的问题 |
| --- | --- |
| `resolve_lineage.py` | 这个名称是否仍然存在?它展开后是什么?它是从哪个谱系衍生出来的? |
| `lineage_prevalence.py` | 这个谱系每周占序列总数的比例是多少?是否在增长? |
| `mutation_profile.py` | 它携带哪些突变?与另一个谱系相比有何不同? |
| `reporting_lag.py` | 数据需要回溯多久，才能被信任? |

以上四个脚本都接受 `--format table|tsv|json` 参数，并把来源信息(实例、数据版本、解析出的字段名、过滤条件)打印到 stderr,因此 `> out.tsv` 既能保持数据干净，又能让来源信息可见。

### 从数据出发，而不是从记忆中的清单出发

```bash
# 不指定任何名称:发现该时间窗口内实际正在流行的是什么
python3 lineage_prevalence.py --top 5 --where country=USA --weeks 12
```

> 备注:在该时间窗口内发现了最常见的 5 个 pangoLineage 取值:
> XFG.1.1、XFG.23.1.3、PY.1.1.1、XFJ.3.1.2、PQ.17

对于"现在正在流行什么"这类问题，这才是正确的第一条命令。若一开始就指定具体谱系名称，就等于预先假设你已经知道哪些谱系是重要的——而这正是本技能存在的意义:消除这种假设。

### 使用某个名称之前先核实它

```bash
python3 resolve_lineage.py XFG.23.1.3 PQ.17 PC.2 NOTALINEAGE
```

```
query        status     unaliased                        parent    recombinant_of  descendants  sequences  detail
XFG.23.1.3   current    XFG.23.1.3                       XFG.23.1  LF.7+LP.8.1.2   6            317        S:A1174V, on C29137T branch
PQ.17        current    XDV.1.5.1.1.8.1.17               NB.1.8.1                  23           931        Alias of XDV.1.5.1.1.8.1.17
PC.2         withdrawn  B.1.1.529.2.86.1.1.16.1.7.2.1.2  LF.7.2.1                  4            25         now LF.7.9; Redesignated as LF.7.9
NOTALINEAGE  unknown    NOTALINEAGE                                                0            n/a        no such name in the live nomenclature
```

(`detail` 列已做精简；每一行真实结果还会引用其所来自的谱系提案。)

只要任意一个名称已被撤销或未知，退出码就是 1,因此可以用它来把关一篇论文的谱系清单。注意 `PC.2` 这一行:它在上游已被撤销，但仍有 25 条序列带着这个标签，因为该实例的分配结果滞后于命名更新。这两个事实同时成立，而且都很重要。

### 流行率与增长趋势

```bash
python3 lineage_prevalence.py "XFG.1.1*" "XFJ*" --where country=USA --weeks 16 --growth
```

```
lineage   week        n   total  proportion  ci_low  ci_high  coverage
XFG.1.1*  2026-05-04  42  80     0.5250      0.4170  0.6308   ok
XFG.1.1*  2026-06-15  3   49     0.0612      0.0210  0.1652   ok
XFG.1.1*  2026-06-29  1   30     0.0333      0.0059  0.1667   low
XFG.1.1*  2026-07-13  0   0                                   low
```

由于每周的监测样本量往往很小，比例值附带的是 Wilson 置信区间。分母尚未填充完整的周会被标记为 `low`,除非加上 `--include-incomplete`,否则不会参与增长趋势拟合。

时间窗口会被扩展到完整的 ISO 周，并在扩展发生时明确说明。如果窗口起始于某周中间，首行只覆盖三天、末行只覆盖四天，二者都无法与中间那些完整的周相比较。

`--growth` 报告的是对数几率(log-odds)相对于时间的加权最小二乘斜率。它是**描述性**的:它会把测序方是谁、在哪里测序、报告速度有多快等一切变化都一并吸收进去。它不是适应度(fitness)或传播力估计值。观测量过少的谱系不会输出斜率——原因见下方的"坑"一览表。

### 突变，以及某项检测是否仍然匹配

```bash
python3 mutation_profile.py "XFJ*" --versus "XFG*" --gene S --since 2026-01-01
```

```
mutation  gene  position  verdict  prop_a  prop_b  n_a  n_b
S:L441R   S     441       gained   1.000   0.000   66   0
S:A475V   S     475       gained   1.000   0.000   68   0
S:K444R   S     444       lost     0.000   0.996   0    5031
S:Q493E   S     493       lost     0.000   0.998   0    5359
```

对于分段基因组(segmented genome)同样适用——`--instance h5n1 --gene HA` 或 `--gene seg4`。对于引物和探针相关的问题，应使用 `--nucleotide`,因为此时起作用的单位不是密码子。

### 判断该信任多久之前的数据

```bash
python3 reporting_lag.py --where country=USA
```

```
lag_days  mean_complete  min_complete  max_complete  cohorts
14        0.456          0.332         0.557         6
30        0.677          0.580         0.822         6
60        0.868          0.802         0.949         6
90        0.939          0.916         1.000         6
```

> 一个队列(cohort)有 90% 的数据会在 90 天内到达。可信任截至 2026-04-28 的采集日期；更晚的一切都应视为临时数据。

在引用任何近期流行率数字**之前**,先运行这个脚本。该曲线因病原体和国家而异，差异很大:对 H5N1 而言，同一项指标在第 14 天返回的完整度是 0%,第 30 天才达到 15%,因此所谓"当前"的 H5N1 图景实际上在长达两个月内都是盲区。

## 会导致悄无声息给出错误答案的坑

以下全部内容均已于 2026-07-27 对实时 API 逐一核实过。这正是本技能选择提供脚本而不是一份操作手册的原因；完整细节见 `references/lapis-api.md`。

| 坑 | 后果 |
| --- | --- |
| 不带通配符的谱系名称不包含其子代 | `pangoLineage=XFG` 返回 4 条序列;`XFG*` 返回 640 条 |
| 结尾的 `*` 需要该字段建有谱系索引 | 在 H5N1 上,`clade=2.3.4.4b` 返回 62,413 条，而 `clade=2.3.4.4b*` 返回 **0** 条——同样的语法，含义却截然相反 |
| 字段名称因实例而异 | `dateFrom` 在 H5N1 上是 400 错误；其采集日期字段是 `sampleCollectionDateRangeLower` |
| 只有 `date` 类型的字段才支持范围查询 | H5N1 把 `sampleCollectionDate` 声明为字符串类型，因此它根本没有 `From`/`To` 这类键 |
| 最近几周的数据不是当时流行情况的样本 | 它们只是"谁报告得最快"的样本；一个美国队列中只有 29% 的数据会在 7 天内到达 |
| LAPIS 不会给重组株标注亲本 | 向它查询 `XFG` 的亲本谱系什么都不会返回；只有 `alias_key.json` 中记录了 `XFG = LF.7 + LP.8.1.2` |
| 已撤销的名称仍会残留在数据中 | `PC.2` 在上游已被重新指定为 `LF.7.9`,但仍有序列带着 `PC.2` 这个标签 |
| 未知名称只在建有索引的字段上才会明显报错 | 建有索引的列会对拼写错误返回 400;未建索引的列则会回答 `0` |
| 突变的 `proportion` 是相对于 `coverage` 计算的 | 而不是相对于所有匹配序列——覆盖度很差的位点，即便只有极少读段也可能显示 1.000 |
| `/sample/aggregated` 拒绝 `limit`/`orderBy` 参数 | 其结果本身没有固有的排序；需要在客户端自行排序 |

## 报告结果

要说明实例、数据版本、过滤条件和时间窗口——一个没有这些信息的流行率数字是无法复现的，因为底层数据库每天都在变化。给出计数的同时也要给出比例，引用置信区间，并在时间窗口太新、不足以支撑估计时明确说明这一点。"过去六周没有可靠的估计值"是一个合理、且往往正确的答案。

## 参考文档

- `references/lapis-api.md` —— 接口端点、过滤语法、各实例间的模式差异、实例注册表，以及全部已验证的坑的完整细节。
- `references/lineage-nomenclature.md` —— Pango 别名与重组株、命名变动情况、Nextstrain 分支(clade)、WHO 标签、流感分支、H5N1 分支与基因型，以及这些命名体系之间如何相互映射。
- `references/surveillance-caveats.md` —— 报告延迟、采样与确认偏倚、分母的选取、置信区间与增长趋势的解读方式，以及这些数据无法支撑的结论。
