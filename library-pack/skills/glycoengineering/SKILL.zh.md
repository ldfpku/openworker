# Glycoengineering(糖工程)

## 概览

糖基化(Glycosylation)是蛋白质最常见、也最复杂的翻译后修饰(post-translational modification, PTM),影响超过 50% 的人类蛋白质。聚糖(glycan)调控蛋白质折叠、稳定性、免疫识别、受体相互作用，以及治疗性蛋白质的药代动力学。糖工程(Glycoengineering)是指对糖基化模式进行理性改造，以提升治疗效果、稳定性或免疫逃逸能力。

**两种主要的糖基化类型**:
- **N-糖基化(N-glycosylation)**:连接在 sequon N-X-[S/T](其中 X ≠ 脯氨酸)中的天冬酰胺(N)上；发生在内质网/高尔基体中
- **O-糖基化(O-glycosylation)**:连接在丝氨酸(S)或苏氨酸(T)上；没有严格的共有基序(consensus motif);主要以 GalNAc 起始

## 何时使用本技能

在以下情形使用本技能:

- **抗体工程**:优化 Fc 糖基化以增强 ADCC、CDC,或降低免疫原性
- **治疗性蛋白质设计**:识别影响半衰期、稳定性或免疫原性的糖基化位点
- **疫苗抗原设计**:改造聚糖屏蔽(glycan shield),使免疫应答聚焦于保守表位
- **生物类似药表征**:比较参比药物与生物类似药之间的聚糖模式
- **药物靶点分析**:糖基化是否影响某个受体的靶点结合?
- **蛋白质稳定性**:N-聚糖通常能稳定蛋白质；识别可用于稳定化突变的位点

## N-糖基化 Sequon 分析

### 扫描 N-糖基化位点

N-糖基化发生在 sequon **N-X-[S/T]**(其中 X ≠ 脯氨酸)处。

```python
import re
from typing import List, Tuple

def find_n_glycosylation_sequons(sequence: str) -> List[dict]:
    """
    Scan a protein sequence for canonical N-linked glycosylation sequons.
    Motif: N-X-[S/T], where X ≠ Proline.

    Args:
        sequence: Single-letter amino acid sequence

    Returns:
        List of dicts with position (1-based), motif, and context
    """
    seq = sequence.upper()
    results = []
    i = 0
    while i <= len(seq) - 3:
        triplet = seq[i:i+3]
        if triplet[0] == 'N' and triplet[1] != 'P' and triplet[2] in {'S', 'T'}:
            context = seq[max(0, i-3):i+6]  # ±3 residue context
            results.append({
                'position': i + 1,   # 1-based
                'motif': triplet,
                'context': context,
                'sequon_type': 'NXS' if triplet[2] == 'S' else 'NXT'
            })
            i += 3
        else:
            i += 1
    return results

def summarize_glycosylation_sites(sequence: str, protein_name: str = "") -> str:
    """Generate a research log summary of N-glycosylation sites."""
    sequons = find_n_glycosylation_sequons(sequence)

    lines = [f"# N-Glycosylation Sequon Analysis: {protein_name or 'Protein'}"]
    lines.append(f"Sequence length: {len(sequence)}")
    lines.append(f"Total N-glycosylation sequons: {len(sequons)}")

    if sequons:
        lines.append(f"\nN-X-S sites: {sum(1 for s in sequons if s['sequon_type'] == 'NXS')}")
        lines.append(f"N-X-T sites: {sum(1 for s in sequons if s['sequon_type'] == 'NXT')}")
        lines.append(f"\nSite details:")
        for s in sequons:
            lines.append(f"  Position {s['position']}: {s['motif']} (context: ...{s['context']}...)")
    else:
        lines.append("No canonical N-glycosylation sequons detected.")

    return "\n".join(lines)

# Example: IgG1 Fc region
fc_sequence = "APELLGGPSVFLFPPKPKDTLMISRTPEVTCVVVDVSHEDPEVKFNWYVDGVEVHNAKTKPREEQYNSTYRVVSVLTVLHQDWLNGKEYKCKVSNKALPAPIEKTISKAKGQPREPQVYTLPPSREEMTKNQVSLTCLVKGFYPSDIAVEWESNGQPENNYKTTPPVLDSDGSFFLYSKLTVDKSRWQQGNVFSCSVMHEALHNHYTQKSLSLSPGK"
print(summarize_glycosylation_sites(fc_sequence, "IgG1 Fc"))
```

### 突变 N-糖基化位点

```python
def eliminate_glycosite(sequence: str, position: int, replacement: str = "Q") -> str:
    """
    Eliminate an N-glycosylation site by substituting Asn → Gln (conservative).

    Args:
        sequence: Protein sequence
        position: 1-based position of the Asn to mutate
        replacement: Amino acid to substitute (default Q = Gln; similar size, not glycosylated)

    Returns:
        Mutated sequence
    """
    seq = list(sequence.upper())
    idx = position - 1
    assert seq[idx] == 'N', f"Position {position} is '{seq[idx]}', not 'N'"
    seq[idx] = replacement.upper()
    return ''.join(seq)

def add_glycosite(sequence: str, position: int, flanking_context: str = "S") -> str:
    """
    Introduce an N-glycosylation site by mutating a residue to Asn,
    and ensuring X ≠ Pro and +2 = S/T.

    Args:
        position: 1-based position to introduce Asn
        flanking_context: 'S' or 'T' at position+2 (if modification needed)
    """
    seq = list(sequence.upper())
    idx = position - 1

    # Mutate to Asn
    seq[idx] = 'N'

    # Ensure X+1 != Pro (mutate to Ala if needed)
    if idx + 1 < len(seq) and seq[idx + 1] == 'P':
        seq[idx + 1] = 'A'

    # Ensure X+2 = S or T
    if idx + 2 < len(seq) and seq[idx + 2] not in ('S', 'T'):
        seq[idx + 2] = flanking_context

    return ''.join(seq)
```

## O-糖基化分析

### 启发式 O-糖基化热点预测

```python
def predict_o_glycosylation_hotspots(
    sequence: str,
    window: int = 7,
    min_st_fraction: float = 0.4,
    disallow_proline_next: bool = True
) -> List[dict]:
    """
    Heuristic O-glycosylation hotspot scoring based on local S/T density.
    Not a substitute for NetOGlyc; use as fast baseline.

    Rules:
    - O-GalNAc glycosylation clusters on Ser/Thr-rich segments
    - Flag Ser/Thr residues in windows enriched for S/T
    - Avoid S/T immediately followed by Pro (TP/SP motifs inhibit GalNAc-T)

    Args:
        window: Odd window size for local S/T density
        min_st_fraction: Minimum fraction of S/T in window to flag site
    """
    if window % 2 == 0:
        window = 7
    seq = sequence.upper()
    half = window // 2
    candidates = []

    for i, aa in enumerate(seq):
        if aa not in ('S', 'T'):
            continue
        if disallow_proline_next and i + 1 < len(seq) and seq[i+1] == 'P':
            continue

        start = max(0, i - half)
        end = min(len(seq), i + half + 1)
        segment = seq[start:end]
        st_count = sum(1 for c in segment if c in ('S', 'T'))
        frac = st_count / len(segment)

        if frac >= min_st_fraction:
            candidates.append({
                'position': i + 1,
                'residue': aa,
                'st_fraction': round(frac, 3),
                'window': f"{start+1}-{end}",
                'segment': segment
            })

    return candidates
```

## 外部糖工程工具

### 1. NetOGlyc 4.0(O-糖基化预测)

用于高精度 O-GalNAc 位点预测的网络服务:
- **URL**:https://services.healthtech.dtu.dk/services/NetOGlyc-4.0/
- **输入**:FASTA 格式的蛋白质序列
- **输出**:逐残基的 O-糖基化概率分数
- **方法**:基于实验验证的 O-GalNAc 位点训练的神经网络

```python
import requests

def submit_netoglycv4(fasta_sequence: str) -> str:
    """
    Submit sequence to NetOGlyc 4.0 web service.
    Returns the job URL for result retrieval.

    Note: This uses the DTU Health Tech web service. Results take ~1-5 min.
    """
    url = "https://services.healthtech.dtu.dk/cgi-bin/webface2.cgi"
    # NetOGlyc submission (parameters may vary with web service version)
    # Recommend using the web interface directly for most use cases
    print("Submit sequence at: https://services.healthtech.dtu.dk/services/NetOGlyc-4.0/")
    return url

# Also: NetNGlyc for N-glycosylation prediction
# URL: https://services.healthtech.dtu.dk/services/NetNGlyc-1.0/
```

### 2. GlycoShield-MD(聚糖屏蔽分析)

GlycoShield-MD 用于分析在分子动力学(MD)模拟过程中，聚糖如何屏蔽蛋白质表面:
- **URL**:https://gitlab.mpcdf.mpg.de/dioscuri-biophysics/glycoshield-md/
- **用途**:在整条 MD 轨迹上绘制蛋白质表面的聚糖屏蔽情况
- **输出**:逐残基的屏蔽比例、可视化结果

```bash
# Installation
uv pip install glycoshield

# Basic usage: analyze glycan shielding from glycosylated protein MD trajectory
glycoshield \
    --topology glycoprotein.pdb \
    --trajectory glycoprotein.xtc \
    --glycan_resnames BGLCNA FUC \
    --output shielding_analysis/
```

### 3. GlycoWorkbench(聚糖结构绘制/分析)

- **URL**:https://www.eurocarbdb.org/project/glycoworkbench
- **用途**:绘制聚糖结构、计算质量数、标注质谱图谱
- **格式**:GlycoCT、IUPAC 简化聚糖命名法

### 4. GlyConnect(聚糖-蛋白质数据库)

- **URL**:https://glyconnect.expasy.org/
- **用途**:查找经过实验验证的糖蛋白及其糖基化位点
- **查询方式**:按蛋白质(UniProt ID)、聚糖结构或组织类型查询

```python
import requests

def query_glyconnect(uniprot_id: str) -> dict:
    """Query GlyConnect for glycosylation data for a protein."""
    url = f"https://glyconnect.expasy.org/api/proteins/uniprot/{uniprot_id}"
    response = requests.get(url, headers={"Accept": "application/json"})
    if response.status_code == 200:
        return response.json()
    return {}

# Example: query EGFR glycosylation
egfr_glyco = query_glyconnect("P00533")
```

### 5. UniCarbKB(聚糖结构数据库)

- **URL**:https://unicarbkb.org/
- **用途**:浏览聚糖结构，按质量数或组成进行搜索
- **格式**:GlycoCT 或 IUPAC 命名法

## 关键糖工程策略

### 针对治疗性抗体

| 目标 | 策略 | 备注 |
|------|----------|-------|
| 增强 ADCC | 在 Fc Asn297 处去岩藻糖基化 | 去岩藻糖基化的 IgG1 对 FcγRIIIa 的结合力提高约 50 倍 |
| 降低免疫原性 | 去除非人源聚糖 | 消除 α-Gal、NGNA 表位 |
| 改善药代动力学半衰期 | 唾液酸化 | 唾液酸化的聚糖能延长半衰期 |
| 降低炎症反应 | 高度唾液酸化 | IVIG 抗炎机制 |
| 构建聚糖屏蔽 | 在表面添加 N-糖基化位点 | 掩蔽脆弱表位(用于疫苗设计) |

### 常用突变

| 突变 | 效果 |
|----------|------|
| N297A/Q(IgG1) | 去除 Fc 糖基化(无糖基化) |
| N297D(IgG1) | 去除 Fc 糖基化 |
| S298A/E333A/K334A | 增强 FcγRIIIa 结合 |
| F243L(IgG1) | 增加去岩藻糖基化 |
| T299A | 去除 Fc 糖基化 |

## 聚糖命名法

### IUPAC 简化命名法(单糖缩写)

| 符号 | 全称 | 类型 |
|--------|-----------|------|
| Glc | 葡萄糖(Glucose) | 己糖(Hexose) |
| GlcNAc | N-乙酰葡糖胺(N-Acetylglucosamine) | HexNAc |
| Man | 甘露糖(Mannose) | 己糖(Hexose) |
| Gal | 半乳糖(Galactose) | 己糖(Hexose) |
| Fuc | 岩藻糖(Fucose) | 脱氧己糖(Deoxyhexose) |
| Neu5Ac | N-乙酰神经氨酸(N-Acetylneuraminic acid,唾液酸) | 唾液酸(Sialic acid) |
| GalNAc | N-乙酰半乳糖胺(N-Acetylgalactosamine) | HexNAc |

### 复合型 N-聚糖结构

```
Typical complex biantennary N-glycan:
Neu5Ac-Gal-GlcNAc-Man\
                       Man-GlcNAc-GlcNAc-[Asn]
Neu5Ac-Gal-GlcNAc-Man/
(±Core Fuc at innermost GlcNAc)
```

## 最佳实践

- **先用 NetNGlyc/NetOGlyc** 进行计算预测，再进行实验验证
- **用质谱验证**:利用糖蛋白质组学(Byonic、Mascot)进行位点特异性的聚糖谱分析
- **考虑位点上下文**:并非所有预测出的 sequon 实际上都会被糖基化(取决于可及性、细胞类型、蛋白质构象)
- **对于抗体**:Fc N297 处的聚糖至关重要——务必首先表征这一位点
- **使用 GlyConnect** 检查目标蛋白是否已有经实验验证的糖基化数据

## 其他资源

- **GlyTouCan**(聚糖结构数据仓库):https://glytoucan.org/
- **GlyConnect**:https://glyconnect.expasy.org/
- **CFG Functional Glycomics**:http://www.functionalglycomics.org/
- **DTU Health Tech 服务器**(NetNGlyc、NetOGlyc):https://services.healthtech.dtu.dk/
- **GlycoWorkbench**:https://glycoworkbench.software.informer.com/
- **综述**:Apweiler R et al. (1999) Biochim Biophys Acta. PMID: 10564035
- **治疗性糖工程综述**:Jefferis R (2009) Nature Reviews Drug Discovery. PMID: 19448661
