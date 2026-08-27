# 基因组坐标(Genomic Coordinates)

## 何时使用

任何时候只要坐标跨越了边界:在两种文件格式之间、在两种工具之间、在两个基因组版本(assembly)之间，或者在基因组与转录本之间。

## 准则

**一个坐标包含三个事实，而不是一个:数值本身、它所采用的约定(convention),以及它是相对于哪个基因组版本(assembly)测量的**。 三者缺一不可，否则这个数字就无法解读。

坐标错误是基因组学中最悄无声息的一类 bug。一个整体偏移一位(off-by-one)的 BED 文件依然能被正常解析、排序和求交集，不会报任何错。一个 GRCh37 的 VCF 与一个 GRCh38 的注释文件做连接(join),依然能返回结果行。一个右移了的插入缺失变异(indel)只是悄悄地无法匹配到它在 ClinVar 中的条目，最终结果就是一个变异被报告为"新发现"。没有任何地方会报错；答案只是错了，而且错得看起来还挺合理。

因此:按照对照表来转换，而不是凭记忆转换，并且只要有参考序列可用，就要对照参考序列进行验证。

## 两种转换方式

```
1-based inclusive(1 起始、含端点)  ->  0-based half-open(0 起始、半开区间) :  start - 1,  end
0-based half-open(0 起始、半开区间)  ->  1-based inclusive(1 起始、含端点) :  start + 1,  end
```

end(终点)坐标永远不变。如果某次转换把两个数字都改动了，那就是错的。

## 各种格式属于哪一类

| 0-based(0 起始)、半开区间(half-open) | 1-based(1 起始)、含端点(inclusive) |
| --- | --- |
| BED、bedGraph、bigWig、narrowPeak | GFF3、GTF、VCF |
| BAM/CRAM(二进制 POS) | SAM(文本 POS) |
| PSL、genePred、refFlat | WIG、Picard interval_list |
| MAF(UCSC 多序列比对) | MAF(TCGA 突变注释) |
| PyRanges、pybedtools | GRanges/IRanges、samtools 与 UCSC 与 Ensembl 的区域字符串 |

两种"MAF"格式都存在，它们的含义不同，而且互相不一致。UCSC 通过 1-based 的浏览器输入框来提供 0-based 的文件。`references/format-conventions.md` 中有包含各格式细节的完整对照表。

```bash
cd skills/genomic-coordinates/scripts

python3 convert_coords.py --list                          # 对照表
python3 convert_coords.py --from bed --to gff chr1 999 1000
python3 convert_coords.py --from ucsc --to bed "chr7:5,530,601-5,530,625"
python3 convert_coords.py --from granges --to pyranges --input regions.tsv
```

```
contig  input                 output           length  status  detail
chr7    chr7:5530601-5530625  5530600-5530625  25      ok
```

长度为零的 BED 特征(`chromStart == chromEnd`,一个合法的插入位点)会被报告为 `unrepresentable`(无法表示),而不是被转换成 `end = start - 1`。只要有任何一个区间是退化的或无效的，退出码就是 1。

## 变异不是区间(Interval)

对于插入缺失变异(indel),VCF 的 `POS` 是**锚定碱基(anchor base)**——即事件*之前*的那个碱基，它本身不发生变化。同一个变化可以用许多种方式写出:`chr1:7:CAC:C`、`chr1:3:CAC:C` 和 `chr1:2:GCA:G` 其实是同一个缺失。在归一化(normalise)之前就做连接、去重或查找变异，会悄无声息地丢失真实的匹配，而且丢失的偏偏是重复序列区域里的匹配，那正是插入缺失变异集中出现的地方。

在做任何比较之前，先归一化——先修剪到简约(parsimony)表示，再相对参考序列左对齐(left-align):

```bash
python3 normalize_variant.py --fasta ref.fa chr1 7 CAC C
python3 normalize_variant.py --fasta ref.fa --split --input cohort.vcf
python3 normalize_variant.py --fasta ref.fa --compare chr1:7:CAC:C chr1:2:GCA:G
```

```
input         normalized    type      pos_shift  ref_check  changed
chr1:7:CAC:C  chr1:2:GCA:G  deletion  5          ok         yes
```

每条记录的 `REF` 都会先与 FASTA 进行核对。出现 `MISMATCH` 意味着变异数据和参考序列使用的是不同的基因组版本——此时应停下来运行 `check_contigs.py`,而不是去调整坐标。多等位基因(multi-allelic)记录必须在归一化**之前**用 `--split` 拆分，绝不能在之后拆分。

HGVS 把插入缺失变异往相反方向移动，即沿转录本方向移到最靠 3' 端的位置。对于负链(minus-strand)基因来说，这与 VCF 的左对齐方向在基因组方向上恰好相反。详情和完整流程见 `references/variant-representation.md`。

## 在信任一次连接(join)之前先检查基因组版本

```bash
python3 check_contigs.py --identify unknown.fa.fai
python3 check_contigs.py variants.vcf annotation.gtf --genome GRCh38.fa.fai
```

```
file          kind    contigs  naming        assembly  detail
ref.fa.fai    sizes   25       plain         GRCh37    24/24 primary chromosome lengths match;
                                                       chrM is 16569 bp, i.e. GRCh37/38 (rCRS MT)
```

该脚本能读取 `.fai`、`.chrom.sizes`、VCF 头信息、SAM 头信息、FASTA、BED,以及 GTF/GFF,依据主要染色体的长度识别基因组版本，并报告两个文件之间做连接会出错的每一种原因:命名不匹配、长度冲突、坐标超出某条 contig 的末端、某个 contig 只存在于其中一个文件里。只要存在任何不兼容之处，退出码就是 1。

**GRCh37 和 hg19 唯一的区别在线粒体上**——16,569 bp(rCRS)对 16,571 bp。核基因组坐标完全相同，所以一条混用了这两个版本的流水线依然能正常运行，只有线粒体 DNA 的结果是错的。`check_contigs.py` 会报告它识别出的是哪一个版本。基因组版本、命名方案、ALT contig,以及 liftover 的陷阱，详见 `references/reference-builds.md`。

## 对照文件自身的格式进行审计

```bash
python3 audit_intervals.py peaks.bed
python3 audit_intervals.py gencode.gtf --genome hg38.chrom.sizes
python3 audit_intervals.py cohort.vcf --genome GRCh38.fa.fai
```

查找坐标错误留下的证据:

| 发现项 | 它证明了什么 |
| --- | --- |
| GFF/GTF 中的 `start_below_one` | 0-based 的数据被放进了 1-based 的文件里；所有内容都整体左移了一个碱基 |
| BED 中的 `many_zero_length` | 1-based 的单碱基特征被写进了 0-based 的文件里 |
| `past_contig_end` | 基因组版本错误，或在 contig 边缘处出现了偏移一位的问题 |
| `mixed_contig_naming` | 任何连接操作都会悄悄地只匹配上其中一个子集 |
| `first_block_offset` | BED12 的 `blockStarts` 被写成了绝对坐标 |
| `not_parsimonious` | 等位基因未经修剪；连接之前需要先归一化 |
| `bad_alt_allele` | VCF 中出现了 Ensembl/VEP 的 `-` 记法，这种记法没有锚定碱基 |

只要存在任何致命发现项，退出码就是 1,因此它可以作为数据目录上的 CI 关卡使用。

## 转录本、CDS 与蛋白质位置

`c.742` 和 `chr17:7,674,220` 都是"位置",但二者之间不能靠算术互相换算。转录本坐标是按转录方向对拼接后的碱基计数的——在负链上表现为基因组坐标递减——而且 `c.1` 指的是起始密码子 `ATG` 中的那个 `A`,而不是转录本的起点。

容易被记错的规则有:不存在 `c.0`;5' UTR 位置为负数,3' UTR 位置带 `*` 号;GFF 的 phase 表示的是要*去掉*多少个碱基才能到达下一个密码子，而不是 `start % 3`;而且一个 `c.` 描述如果没有带版本号的转录本编号(accession),就毫无意义，因为同一个变异在不同的转录本中编号方式并不相同。`references/transcript-coordinates.md` 中有转换流程和边界情况的说明。

请使用持有转录本模型的工具来完成转换——VEP、`bcftools csq`、Mutalyzer、`hgvs` 包——而不要手工换算。

## 报告结果

每次都要在坐标旁边注明基因组版本。`chr7:5,530,601-5,530,625` 不是一个明确的位置;`chr7:5,530,601-5,530,625 (GRCh38)` 才是。在列标题或文件文档中说明某个坐标列采用的是哪种约定。当某次转换产生了结果时，说明转换的方向是什么。

## 参考资料

- `references/format-conventions.md` —— 每种格式的约定，含各格式细节、BED12 区块规则、区域字符串语法，以及各工具的行为。
- `references/variant-representation.md` —— VCF 等位基因约定、归一化算法、等价性检查、多等位基因拆分，以及 HGVS 与 VCF 的分歧之处。
- `references/reference-builds.md` —— 基因组版本特征、GRCh37 与 hg19 的区别、ALT contig、命名方案，以及 liftover 的常见失败模式。
- `references/transcript-coordinates.md` —— 基因组 ↔ 转录本 ↔ CDS ↔ 蛋白质、HGVS 编号方式、phase,以及转录本的选择。
