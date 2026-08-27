# Matchms

## 用途与范围

Matchms 是一个用于导入、清洗、处理及比较串联质谱（tandem mass spectra）的 Python 软件包。本技能针对的是 **matchms 0.33.1**（发布于 2026-06-08），并纠正了若干旧教程未能反映的破坏性 API 变更。

在以下场景使用 matchms：

- MS/MS 谱库检索及待测样本与参考谱之间的打分比对
- 元数据统一化处理、加合离子（adduct）/前体离子（precursor）处理，以及峰过滤
- 余弦（cosine）、修正余弦（modified-cosine）、中性丢失（neutral-loss）、近似（approximate）及熵（entropy）打分
- 结构化的打分矩阵、最佳匹配提取，以及谱图网络
- MGF、MSP、mzML、mzXML、JSON、mzSpecLib，以及 metabolomics-USI 相关工作流

不要将 matchms 用作以下用途的替代方案：

- LC-MS 特征检测、色谱对齐、肽段鉴定或蛋白质定量——请使用 pyopenms
- 厂商原始文件格式转换——请先转换为 mzML/mzXML
- 经过验证的化合物鉴定协议——相似度只是证据，并非身份确认的证明

## 安装已验证的发布版本

创建或激活一个环境，然后安装本技能所使用的版本：

```bash
uv pip install "matchms==0.33.1"
```

核实运行环境：

```bash
uv run python -c "import matchms; print(matchms.__version__)"
```

Matchms 0.33.1 支持 Python 3.10-3.14，并将 RDKit 作为常规依赖项一并安装。旧版的 `matchms[chemistry]` extra 不再属于当前软件包元数据的一部分。

## 操作工作流

1. **检查输入内容**。 记录格式、谱图数量、MS 级别、前体离子覆盖情况、离子模式（ion mode）、峰值数量，以及标识符字段。
2. **加载时启用元数据统一化处理**，除非有意要保留原始来源的键名。
3. **对待测谱与参考谱应用完全相同的峰处理步骤**。 当参考谱的注释信息更丰富时，将元数据的丰富处理单独进行。
4. **明确丢弃无效的谱图**。 许多 `require_*` 过滤器会返回 `None`。
5. **根据科学问题本身来选择打分方法**，而不是图方便。修正余弦及中性丢失打分要求存在有效的 `precursor_mz`。
6. **在打分之前先估算 `len(references) * len(queries)`。** 稀疏的结果容器并不会自动避免对每一个被请求的组合都进行计算。
7. **报告打分设置及证据**。 包含容差（tolerance）、预处理方式、打分方法名称、可用时的匹配峰数量，以及候选物的元数据。
8. **对最佳匹配结果进行可视化及化学层面的验证**。 使用镜像图（mirror plot）、前体离子一致性、离子/加合离子兼容性，以及其他正交证据。

## 当前 API 的护栏（Guardrails）

以下要点可以避免 0.33 之前示例代码中最常见的失败情形：

- 使用 `ModifiedCosineGreedy` 或 `ModifiedCosineHungarian`；`ModifiedCosine` 已在 0.32.0 中被移除。
- 不要调用 `add_losses()`。该方法已在 0.27.0 中被移除；请直接使用 `spectrum.losses`、`spectrum.compute_losses(...)`，或 `NeutralLossesCosine`。
- `SpectrumProcessor` 本身不可被调用（not callable）。请使用 `process_spectrum()` 或 `process_spectra()`。
- `process_spectra()` 返回的是 `(processed_spectra, processing_report)`。
- `Scores.scores` 是一个 `StackedSparseArray`，通常带有独立的结构化字段，例如 `CosineGreedy_score` 与 `CosineGreedy_matches`。
- `scores_by_query()` 返回的是 `(reference_spectrum, score_record)` 这样的成对结果，而不是参考谱的索引值。
- 参数命名中优先使用 `spectra`。旧的拼写方式 `spectrums` 已被弃用。
- 绝不要从不受信任的来源加载 pickle 文件；反序列化（unpickling）可能会执行任意代码。

关于从旧版到当前版本的完整映射，参见 `references/migration.md`。

## 快速入门：清洗并检索一个谱库

```python
from matchms import SpectrumProcessor, calculate_scores
from matchms.filtering import (
    default_filters,
    normalize_intensities,
    require_minimum_number_of_peaks,
    select_by_relative_intensity,
)
from matchms.importing import load_spectra
from matchms.similarity import ModifiedCosineGreedy


def load_and_process(path):
    spectra = [default_filters(spectrum) for spectrum in load_spectra(path)]
    processor = SpectrumProcessor(
        [
            normalize_intensities,
            (select_by_relative_intensity, {"intensity_from": 0.01}),
            (require_minimum_number_of_peaks, {"n_required": 5}),
        ]
    )
    processed, _ = processor.process_spectra(
        spectra,
        progress_bar=False,
        create_report=False,
    )
    return processed


references = load_and_process("library.msp")
queries = load_and_process("queries.mgf")

metric = ModifiedCosineGreedy(tolerance=0.02)
scores = calculate_scores(
    references=references,
    queries=queries,
    similarity_function=metric,
)

score_name = "ModifiedCosineGreedy_score"
matches_name = "ModifiedCosineGreedy_matches"
for query in queries:
    ranked = scores.scores_by_query(query, name=score_name, sort=True)
    for reference, values in ranked[:5]:
        print(
            query.get("spectrum_id", query.get("id")),
            reference.get("compound_name", reference.get("spectrum_id")),
            float(values[score_name]),
            int(values[matches_name]),
        )
```

`SpectrumProcessor` 会依据 matchms 的过滤器顺序自动排列内置过滤器。聚合型可调用对象 `default_filters` 并不在该注册表内，因此需要像上面那样先单独运行它，或者展开其内部的九个组件过滤器。检查 `processor.processing_steps`，并将其与结果一并保留。

## 成对打分（Pair Scoring）

相似度类提供了 `pair()` 方法，用于对单个参考谱/待测谱进行打分。余弦系（Cosine-family）方法的结果是结构化的 NumPy 标量：

```python
from matchms.similarity import CosineGreedy

result = CosineGreedy(tolerance=0.02).pair(reference, query)
similarity = float(result["score"])
matched_peaks = int(result["matches"])
```

对于诸如 `FlashSimilarity` 这类面向矩阵的方法，请使用 `calculate_scores()`；其单对（single-pair）计算路径虽然受支持，但刻意未做优化。

## 选择相似度计算方法

- `CosineGreedy` —— 标准的峰值余弦相似度，采用贪心（greedy）峰值匹配。
- `CosineHungarian` —— 精确匹配算法；速度较慢，适用于基准测试。
- `CosineLinear` —— 当前的线性缩放余弦实现。
- `ModifiedCosineGreedy` —— 允许存在前体离子偏移（precursor-delta-shifted）的匹配；常用于类似物检索（analog search）。
- `ModifiedCosineHungarian` —— 精确的修正余弦匹配算法。
- `NeutralLossesCosine` —— 比较由前体离子与碎片离子计算得出的中性丢失。
- `BlinkCosine` —— 面向大型矩阵的快速 BLINK 风格余弦近似算法。
- `FlashSimilarity` —— 使用谱图熵或余弦，配合碎片、中性丢失或混合匹配方式的优化矩阵打分方法。
- `BinnedEmbeddingSimilarity` —— 分箱（binned）后的谱图向量，并可选配近似最近邻索引。
- `PrecursorMzMatch`、`ParentMassMatch`、`MetadataMatch` —— 候选物筛选掩码或元数据约束条件，而非丰富的谱图打分。
- `FingerprintSimilarity` —— 分子结构相似度；它并非谱图相似度，且要求由有效结构预先生成指纹（fingerprint）。

在选择一个快速方法、组合多个打分结果，或解读结构化输出之前，请先阅读 `references/similarity.md`。

## 大规模比对

对于单个集合内部的全对全（all-vs-all）打分，设置 `is_symmetric=True`：

```python
scores = calculate_scores(
    references=spectra,
    queries=spectra,
    similarity_function=CosineGreedy(tolerance=0.02),
    array_type="sparse",
    is_symmetric=True,
)
```

对于以前体离子作为门控条件的检索，先计算并过滤 `PrecursorMzMatch`，然后只通过 `Pipeline` 或 `Scores.calculate(...)` 对保留下来的坐标计算谱图度量指标。参见 `references/workflows.md`。

不要选定一个通用的"鉴定阈值"。打分的分布情况取决于预处理方式、质量精度、碰撞条件、谱库质量以及所用度量方法。对于余弦系方法，至少要同时保留打分数值和匹配峰数量。

## 内置的谱库检索 CLI

`scripts/library_search.py` 提供了一个可复现的待测谱与谱库比对检索功能，包含当前的打分提取、成对数量上限、预处理，以及 CSV 输出：

```bash
uv run python scripts/library_search.py \
  queries.mgf library.msp hits.csv \
  --metric modified \
  --tolerance 0.02 \
  --top-k 10 \
  --min-score 0.6 \
  --min-matches 5
```

运行 `--help` 查看快速度量方法、预处理选项、标识符字段、覆盖控制，以及显式的大矩阵覆盖开关。

## 谱图对象与可视化

```python
import numpy as np
from matchms import Spectrum

spectrum = Spectrum(
    mz=np.array([100.0, 150.0, 200.0]),
    intensities=np.array([0.2, 1.0, 0.4]),
    metadata={"spectrum_id": "query-1", "precursor_mz": 250.5},
)

print(spectrum.peaks.mz)
print(spectrum.get("precursor_mz"))
losses = spectrum.compute_losses(loss_mz_from=5.0, loss_mz_to=200.0)
spectrum.plot()
spectrum.plot_against(reference_spectrum)
```

## 参考资料

只阅读当前任务所需的那一份参考资料：

- `references/importing_exporting.md` —— 各种格式、返回类型、通用 I/O、mzSpecLib、打分结果序列化，以及 pickle 安全性
- `references/filtering.md` —— 当前的过滤器目录、克隆（clone）/`None` 语义、默认过滤器、排序方式，以及 `SpectrumProcessor`
- `references/similarity.md` —— 当前全部的相似度计算类、输出内容、候选物掩码、性能，以及结果解读
- `references/workflows.md` —— 谱库检索、稀疏化门控、`Pipeline`、网络图、绘图，以及数据来源溯源
- `references/migration.md` —— 破坏性变更及已弃用的 API
- `references/sources.md` —— 本次更新所依据的权威文档、发行说明、用户指南及科学出版物

## 不可协商的检查项

- 绝不要将未经处理的待测谱与经过不同方式处理的参考谱进行比对。
- 绝不要在没有有效前体离子元数据的情况下使用修正余弦或中性丢失打分。
- 绝不要假定 `Scores` 中的某个值是一个普通的浮点数；应检查 `score_names`。
- 绝不要仅凭一个较高的相似度打分就认定鉴定结果已被确认。
- 绝不要反序列化不受信任的 pickle 数据。
- 绝不要在未估算成对数量的情况下，启动一次无边界限制的全对全比对。
