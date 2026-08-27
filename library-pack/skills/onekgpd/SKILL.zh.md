# OneKGPd：面向 1000 Genomes Project 的个体级查询

## 范围

本技能查询 1000 Genomes Project 数据集——即在 GRCh38 装配版本上、由 3,202 名个体组成的扩展高覆盖度全基因组测序队列。所有结果均取自该队列，技能返回的样本名（例如
`HG00096` 或 `NA21130`）标识的都是该队列中的参与者。

查询针对的是该队列的个体级基因型数据。这支持两类互补的问题：在某区域内（无论是在整个队列范围内，还是在指定的一组个体范围内）选取所携带的**变异（variants）**；以及选取携带符合给定条件的变异的**个体（individuals）**。变异的筛选可以按等位基因频率、预测后果（consequence）、临床意义、AlphaMissense 分类以及下文所列的其他注释维度进行。同时也可以查询两个指定个体之间的亲缘关系。

变异所处的基因型状态——杂合（heterozygous）还是纯合（homozygous）——是查询可以指定的一个条件；结果以变异或样本名的形式返回，而不是以原始基因型的形式返回。

## 何时使用

**在以下情况下使用本技能**：

-   查找在一个或多个区域内、符合某些条件的、在整个队列范围内被携带的**变异**（`select-variants`）。
-   查找在一个或多个区域内、符合某些条件的、在指定一组个体中被携带的**变异**（`select-variants-in-samples`）。
-   查找**哪些 1000 Genomes 个体**在某区域或一组区域内携带符合某些条件的变异（`select-samples`）。
-   统计携带特定变异的个体数量（`count-samples`）。
-   将任意变异查询限定为**仅杂合携带或仅纯合携带**，或同时查询两者（默认）。
-   识别在单个位点上是**纯合参考基因型**（homozygous reference）的个体（`select-samples-hom-ref`）。
-   确定两个指定的 1000 Genomes 个体之间的**亲缘关系（relatedness）**——包括亲缘度（双胞胎 / 一级 / 二级 / 三级 / 无亲缘关系）以及 KING 亲缘系数（`kinship`）。
-   获取**数据集总体统计信息**——样本数、性别分布、变异数、装配版本（`dataset-info`）。
-   变异筛选可以按 KGP 等位基因频率、gnomAD 4.1 外显子组和 gnomAD 4.1 基因组等位基因频率、AlphaMissense 评分与 AlphaMissense 分类、ClinVar 临床意义（202502 版本）以及 VEP 注释（影响程度、生物类型、特征类型、变异类别、后果）来指定。

**不要将本技能用于**：

-   将基因符号、rsID 或转录本解析为坐标，或获取参考序列。请先解析坐标（参见下文的“坐标溯源”一节），再用解析出的 GRCh38 区域查询本技能。
-   1000 Genomes Project 以外的任何队列——本技能只服务于该数据集。

## 前置条件

1.  **`uv`**：本技能的脚本通过 `uv run` 运行，它会读取脚本内嵌的依赖元数据，并临时配置一个运行环境。请确保 `uv` 已安装并在 PATH 中（<https://docs.astral.sh/uv/>）。
2.  **数据使用条款**：1000 Genomes Project 的数据是开放的；使用者应了解 1000 Genomes Project / IGSR 的数据使用条款
    （<https://www.internationalgenome.org/data>）。
3.  **访问限制**：无需配置 API key，无需 `.env` 文件，也无需配置速率限制令牌。
4.  **无需凭证**

## 核心规则

-   **使用封装脚本**：务必执行技能提供的辅助脚本，而不要自行构造客户端调用或网络请求。变异/样本/亲缘关系查询使用
    `scripts/onekgpd_api.py`（它处理连接、流式传输、分页和 JSON 序列化）；样本/群体元数据查询使用
    `scripts/onekgpd_meta.py`（离线运行，参见
    [样本与群体元数据](#样本与群体元数据离线)）。
-   **坐标必须先针对权威来源进行解析** ——参见
    [坐标溯源（强制性首要步骤）](#坐标溯源强制性首要步骤)。这是强制要求，不是建议。
-   **先计数再选取**：每一种变异和样本的选取命令都配有对应的计数命令。先调用计数命令来估算结果集规模，只有在计数结果可控的情况下再进行选取。
-   **合子状态默认为两者都包含**：选取和计数命令默认同时包含杂合和纯合携带。当问题专门针对某一种状态时，用 `--het-only`
    或 `--hom-only` 加以限制。（若要同时获取两者，无需传入任何参数。）
-   **输出**：脚本会把完整的 JSON 写入文件（`--output`，默认位于
    `/tmp/` 下），并在标准输出打印一份简要摘要。不要把大型 JSON 文件整个读入上下文——请使用
    `jq` 或一个临时的 `uv run python` 脚本片段来提取字段。

## 坐标溯源（强制性首要步骤）

在进行任何基于区域的查询之前，必须先针对权威来源（例如 Ensembl）将基因或特征解析为
**GRCh38** 坐标，再用解析出的坐标进行查询。装配版本必须明确指定，且基因范围在使用前必须解析为精确的位置。这是结构性要求，而非建议：数据源一侧没有任何护栏能捕获一个位置错误的区域，因此一个未经验证的坐标会在没有任何报错的情况下，得到针对错误位置的结果。

```bash
# Resolve gene symbol -> GRCh38 region with an authoritative source FIRST,
# then pass the verified coordinates to the OneKGPd query below.
```

> [!CAUTION]
> 该数据集基于 GRCh38。GRCh37 坐标，或任何与目标特征在 GRCh38 上不正确对应的区域，都会在不报错的情况下返回针对错误位置的结果。在查询之前请务必核实装配版本和已解析的坐标。

## 命令选择指南

将问题与对应命令匹配。计数类命令开销很小，应先于其对应的选取类命令执行。

-   某区域内哪些个体携带符合条件的变异 → 先 `count-samples`
    再 `select-samples`
-   某区域内、整个队列范围内携带了哪些变异 → 先 `count-variants`
    再 `select-variants`
-   某区域内、指定一组个体中携带了哪些变异 →
    先 `count-variants-in-samples` 再 `select-variants-in-samples`
-   谁在单个位点上是纯合参考基因型 → 先 `count-samples-hom-ref`
    再 `select-samples-hom-ref`
-   两个指定个体之间的亲缘关系（亲缘度 + 系数）→
    `kinship`
-   数据集总体统计（样本数、性别分布、变异总数、装配版本）→
    `dataset-info`

## 注释筛选条件（变异与样本的选取/计数命令共用）

所有变异与样本选取/计数命令（`count-variants`、
`select-variants` 及其 `-in-samples` 形式、`count-samples`、`select-samples`）
都接受相同的注释筛选条件。不同筛选字段之间以**与**（AND）关系组合；同一字段内的多个值之间以**或**（OR）关系组合。枚举值不区分大小写（例如
`missense_variant` 或 `MISSENSE_VARIANT` 均可）。

这些是在服务端应用的选取条件。已选取变异所返回的字段列在
[返回变异的命令](#返回变异的命令)一节；用于筛选的条件不一定会在返回的变异中被回显。

-   `--af-lt` / `--af-gt`：1000 Genomes 数据集等位基因频率的上下界
-   `--gnomad-exomes-af-lt` / `--gnomad-exomes-af-gt`：gnomAD v4.1 外显子组等位基因频率的上下界
-   `--gnomad-genomes-af-lt` / `--gnomad-genomes-af-gt`：gnomAD v4.1 基因组等位基因频率的上下界
-   `--clin-significance`：ClinVar 临床意义术语，逗号分隔（例如 `PATHOGENIC,LIKELY_PATHOGENIC`）
-   `--consequence`：Sequence Ontology 后果术语，逗号分隔（例如 `MISSENSE_VARIANT,STOP_GAINED`）
-   `--impact`：VEP 影响程度，逗号分隔（`HIGH,MODERATE,LOW,MODIFIER`）
-   `--variant-type`、`--feature-type`、`--bio-type`：SO 变异类别 / VEP 特征类型 / VEP 生物类型，逗号分隔
-   `--alpha-missense-class`：`AM_LIKELY_BENIGN,AM_LIKELY_PATHOGENIC,AM_AMBIGUOUS`（逗号分隔）
-   `--alpha-missense-score-lt` / `--alpha-missense-score-gt`：AlphaMissense 评分的上下界
-   `--biallelic-only` / `--multiallelic-only`
-   `--exclude-males` / `--exclude-females`
-   `--min-len-bp` / `--max-len-bp`：替代等位基因长度的上下界（以 bp 为单位）

> [!NOTE]
> `--alpha-missense-class` 与 `--alpha-missense-score-*` 互斥
> （当设置了评分边界时，引擎会忽略分类条件）。`--biallelic-only`
> 与 `--multiallelic-only` 互斥。`--exclude-males` 与
> `--exclude-females` 互斥。当 `*-gt` 边界大于等于其对应的 `*-lt`
> 边界时会定义出一个空区间，不会返回任何结果。

> [!NOTE]
> 等位基因频率字段用 `0.0` 表示“在该来源中不存在”。因此
> `--gnomad-exomes-af-gt 0` 选取的是*确实*存在于 gnomAD 外显子组中的变异；返回结果中的
> `gnomad_exomes_af` 为 `0.0` 意味着该变异在 gnomAD 外显子组中不存在。gnomAD 基因组等位基因频率也遵循同样的约定。
> 反过来，`--gnomad-exomes-af-lt` / `--gnomad-genomes-af-lt` 边界会**包含**
未注释的变异：“gnomAD 中 AF < X”会包含 gnomAD AF = 0（即未注释）的变异；如需要求变异确实存在于 gnomAD 中，请配合使用 `--gnomad-*-af-gt 0`。

> [!NOTE]
> `am_score` 为 `0.0` 表示未被 AlphaMissense 评分或未被其注释——并不表示“良性（benign）”。
> 真正的 AlphaMissense 评分始终大于 0。

## 快速入门

```bash
# Step 1. Resolve coordinates against an authoritative source — see Coordinate Provenance.
#    example: BRCA1: chr17:43044292-43170245
# Step 2. Size the result set: how many individuals carry predicted likely-pathogenic
#    missense variants in this region?
uv run scripts/onekgpd_api.py count-samples \
  --chrom chr17 --start 43044292 --end 43170245 \
  --consequence MISSENSE_VARIANT \
  --alpha-missense-class AM_LIKELY_PATHOGENIC \
  --output /tmp/count.json
# Step 3. If the count is manageable, list those individuals.
uv run scripts/onekgpd_api.py select-samples \
  --chrom chr17 --start 43044292 --end 43170245 \
  --consequence MISSENSE_VARIANT \
  --alpha-missense-class AM_LIKELY_PATHOGENIC \
  --output /tmp/samples.json
# Step 4: For that set of individuals, see the actual variants they carry.
uv run scripts/onekgpd_api.py select-variants-in-samples \
  --chrom chr17 --start 43044292 --end 43170245 \
  --samples HG03169,NA20506 \
  --consequence MISSENSE_VARIANT --alpha-missense-class AM_LIKELY_PATHOGENIC \
  --output /tmp/variants.json
```

## 命令

每个命令都会把完整的 JSON 写入文件（`--output PATH`，默认写入一个临时文件），
并在标准输出打印一份简要摘要。所有区域/样本命令共用以下部分：区域输入
（`--chrom`/`--start`/`--end`，可选 `--ref`/`--alt`，或一个或多个可重复的
`--region CHR:START-END`）、合子状态标志
（`--het-only`/`--hom-only`，默认两者都包含）以及上文的注释筛选条件。
完整的逐参数表格见
[references/onekgpd_commands.md](references/onekgpd_commands.md)。

### 返回变异的命令

`select-*` 返回匹配的变异；`count-*` 返回一个整数计数。

-   `count-variants` —— 统计整个队列范围内某区域内的变异数量。
-   `select-variants` —— 选取整个队列范围内某区域内的变异。使用 `--limit N`
    （硬性上限，默认 200）**或** `--page-size N`（分页获取完整结果集）；两者互斥。当达到上限时摘要会标记
    `truncated`。
-   `count-variants-in-samples` —— 与 `count-variants` 相同，但限定于
    `--samples NAME1,NAME2,...`（必填）。
-   `select-variants-in-samples` —— 与 `select-variants` 相同，但限定于
    `--samples NAME1,NAME2,...`（必填）。

每个返回的变异都携带以下 22 个字段：`chr`、`start`、`end`、`ref`、
`alt`、`af`、`ac`、`an`、`hom_samples`、`het_samples`、`mis_samples`、
`hom_samples_fx`、`het_samples_fx`、`mis_samples_fx`、`hom_samples_mxy`、
`het_samples_mxy`、`mis_samples_mxy`、`gnomad_exomes_af`、`gnomad_genomes_af`、
`am_score`、`amino_acids`、`biallelic`。
ClinVar 临床意义和 VEP 后果只是筛选条件，不会被返回。完整的 schema 见：
[references/onekgpd_commands.md](references/onekgpd_commands.md)。

### 返回样本的命令

-   `count-samples` —— 统计在某区域内携带匹配变异的个体数量。
-   `select-samples` —— 列出携带匹配变异的个体名。
    支持 `--skip N` 和 `--limit N`。只返回名字；若要查看某个个体是因哪些变异而符合条件，请把这些名字传入
    `select-variants-in-samples`。

### 纯合参考基因型命令

通过 `--chrom` + `--position`（单个位置，而非区域）指定。

-   `count-samples-hom-ref` —— 统计在该位置上为 0/0 基因型的个体数量。
    该计数是一个哨兵值：`-1` 表示该位置根本不存在变异；
    `0` 表示存在变异但没有个体是纯合参考基因型；`>0` 表示纯合参考基因型个体的数量。摘要会说明属于哪一种情况。
-   `select-samples-hom-ref` —— 列出在该位置上为 0/0 基因型的个体。

### 亲缘关系命令

-   `kinship --sample1 NAME --sample2 NAME` —— 两个指定个体之间的亲缘关系：亲缘度（`TWINS_MONOZYGOTIC` /
    `FIRST_DEGREE` /
    `SECOND_DEGREE` / `THIRD_DEGREE` / `UNRELATED`）以及 KING 亲缘系数
    （`phi_bwf`）。

### 数据集元数据命令

-   `dataset-info` —— 数据集总体统计：`samples_total`（3,202）、女性/男性分布、
    `variants_total`、`assembly`（GRCh38）以及队列构成明细。不需要区域参数；也可作为连通性检查使用。

## 样本与群体元数据（离线）

群体、性别、家系（pedigree）和超级群体（superpopulation）方面的问题，由另一个脚本
`scripts/onekgpd_meta.py` 从技能内置的一个数据文件中解答——**无需网络、无需凭证、无需坐标**。样本 ID 与变异命令所用的名字相同，因此这两层可以组合使用（例如先按群体挑选一个队列，再查询其变异）。运行方式为
`uv run scripts/onekgpd_meta.py <command>`。

该队列包含 5 个超级群体（`AFR`、`AMR`、`EAS`、`EUR`、`SAS`）和 26
个群体。群体/超级群体的值匹配时**不区分大小写**，可用简码或全名；**样本 ID 则区分大小写**。

-   `sample-metadata --samples NA19240,HG00096` —— 给定样本的家系、性别、父母、
    子女、群体、超级群体以及 phase3 状态。
-   `list-populations` —— 全部 26 个群体，包含超级群体归属和样本数
    （用于查找有效取值）。
-   `list-superpopulations` —— 5 个超级群体，包含样本数和所含的各群体。
-   `population-stats --populations YRI [--populations CHS …]` —— 每个群体的性别
    分布、phase3 计数以及三人家系（trio）成员情况。多个值请重复 `--populations` 传参（因为全名中含有逗号，所以不用逗号分隔）。
-   `superpopulation-summary --superpopulations EAS [--superpopulations EUR …]` ——
    每个超级群体的总计以及按群体细分的明细。
-   `select-samples-by-population --population YRI` 和/或 `--superpopulation AFR`，
    可选 `--skip`/`--limit`（默认 0 / 50，最大 3202）—— 某群体和/或超级群体内的样本 ID；
    两者都给出时取交集。将这些名字传入
    `select-variants-in-samples` 即可查看其变异。

完整的参数表和 JSON 输出 schema 见 [references/onekgpd_commands.md](references/onekgpd_commands.md)。

## 典型工作流

### 先找出哪些个体，再看他们携带哪些变异

```bash
# Step 1: resolve gene -> verified GRCh38 region (authoritative source).
# Step 2: count individuals carrying a qualifying variant in the region.
uv run scripts/onekgpd_api.py count-samples \
  --chrom <chr> --start <start> --end <end> \
  --consequence MISSENSE_VARIANT --alpha-missense-class AM_LIKELY_PATHOGENIC \
  --output /tmp/n.json
# Step 3: list those individuals.
uv run scripts/onekgpd_api.py select-samples \
  --chrom <chr> --start <start> --end <end> \
  --consequence MISSENSE_VARIANT --alpha-missense-class AM_LIKELY_PATHOGENIC \
  --output /tmp/who.json
# Step 4: for that set of individuals, see the actual variants they carry.
uv run scripts/onekgpd_api.py select-variants-in-samples \
  --chrom <chr> --start <start> --end <end> \
  --samples <name1,name2,...> \
  --consequence MISSENSE_VARIANT --alpha-missense-class AM_LIKELY_PATHOGENIC \
  --output /tmp/variants.json
```

### 目标位点上的纯合参考基因型携带者

```bash
# After identifying a position of interest (verified coordinate):
uv run scripts/onekgpd_api.py count-samples-hom-ref \
  --chrom <chr> --position <pos> --output /tmp/homref_n.json
uv run scripts/onekgpd_api.py select-samples-hom-ref \
  --chrom <chr> --position <pos> --output /tmp/homref.json
```

## 常见错误

-   **错误**：使用未经验证的坐标进行查询。
    **修正**：始终先针对权威来源将基因/特征解析为
    GRCh38 坐标。
    位置错误的区域会在不报错的情况下返回针对错误位置的结果。
-   **错误**：在选取命令之前没有先调用其对应的计数命令。
    **修正**：先计数；选取结果集可能非常大。
-   **错误**：假设 GRCh37 坐标也能正常使用。
    **修正**：该数据集仅支持 GRCh38。

## 参考资料

-   [references/onekgpd_commands.md](references/onekgpd_commands.md) —— 完整的
    逐命令参数表以及返回变异的输出 schema。
-   [references/annotation_vocabularies.md](references/annotation_vocabularies.md)
    —— CSV 筛选参数所接受的受控词表术语
    （后果、影响程度、生物类型、特征类型、ClinVar 临床意义、
    AlphaMissense 分类、变异类别）。
-   1000 Genomes Project / IGSR：https://www.internationalgenome.org/
-   1000 Genomes Project 数据集在线查询：https://dnaerys.org/online/
