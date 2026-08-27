# Statsmodels：统计建模与计量经济学

## 概述

Statsmodels 是 Python 中首屈一指的统计建模库，为估计、推断，以及横跨
各类统计方法的诊断提供了完整工具。将本技能应用于严谨的统计分析，
从简单的线性回归到复杂的时间序列模型与计量经济学分析，皆可覆盖。

## 当前兼容性

示例针对 2025 年 12 月 5 日发布的 statsmodels 0.14.6 版本。为保证
环境可复现，请固定主要包的版本：

```bash
uv pip install statsmodels==0.14.6
```

对于稳定的高层导入，使用 `statsmodels.api` 与
`statsmodels.formula.api`；当示例需要用到更新或更专门的类（例如
`HurdleCountModel`）时，则直接导入相应模块。

## 何时使用本技能

在以下情形应当使用本技能：
- 拟合回归模型（OLS、WLS、GLS、分位数回归）
- 执行广义线性建模（逻辑回归、泊松回归、伽马回归等）
- 分析离散结果变量（二元、多分类、计数、有序）
- 进行时间序列分析（ARIMA、SARIMAX、VAR、预测）
- 运行统计检验与诊断
- 检验模型假设（异方差性、自相关、正态性）
- 检测离群值与高影响力观测点
- 比较模型（AIC/BIC、似然比检验）
- 估计因果效应
- 生成可供发表的统计表格与推断结果

## 快速上手、功能范围与模型选择

- [references/quick_start_guide.md](references/quick_start_guide.md)：OLS、
  逻辑回归、ARIMA 与 GLM 的最简示例，以及如何解读汇总结果。
- [references/modeling_capabilities.md](references/modeling_capabilities.md)：
  线性模型、GLM、离散选择模型、时间序列，以及统计检验与诊断。
- [references/model_selection.md](references/model_selection.md)：R 风格的
  公式 API，以及模型比较。
- 各主题详情：[references/linear_models.md](references/linear_models.md)、
  [references/glm.md](references/glm.md)、
  [references/discrete_choice.md](references/discrete_choice.md)、
  [references/time_series.md](references/time_series.md)，以及
  [references/stats_diagnostics.md](references/stats_diagnostics.md)。

statsmodels 面向的是*推断*——标准误、置信区间，以及假设检验。当目标
是预测、且系数无需解释时，应选用 scikit-learn。

## 最佳实践

### 数据准备

1. **始终添加常数项**：使用 `sm.add_constant()`，除非要排除截距
2. **检查缺失值**：在拟合前处理或填补缺失值
3. **按需缩放**：有助于收敛与解释（但树模型不需要）
4. **编码分类变量**：使用公式 API 或手动进行哑变量编码

### 模型构建

1. **从简单开始**：先建立基础模型，再按需增加复杂度
2. **检验假设**：检验残差、异方差性、自相关性
3. **使用合适的模型**：让模型与结果变量类型相匹配（二元 → Logit，
   计数 → 泊松）
4. **考虑替代方案**：若假设不成立，改用稳健方法或其他模型

### 推断

1. **报告效应量**：不要只报告 p 值
2. **使用稳健标准误**：当存在异方差性或聚类结构时
3. **多重比较**：在检验多个假设时进行校正
4. **置信区间**：始终与点估计一并报告

### 模型评估

1. **检查残差**：绘制残差对拟合值图、Q-Q 图
2. **影响力诊断**：识别并核查高影响力观测点
3. **样本外验证**：在留出集上测试，或进行交叉验证
4. **比较模型**：非嵌套模型用 AIC/BIC，嵌套模型用 LR 检验

### 报告

1. **完整的汇总结果**：使用 `.summary()` 获取详细输出
2. **记录决策过程**：注明变换方式、被排除的观测点
3. **谨慎解读**：考虑连接函数的影响（例如对数连接下的 exp(β)）
4. **可视化**：绘制预测值、置信区间、诊断图

## 常见工作流

### 工作流 1：线性回归分析

1. 探索数据（绘图、描述性统计）
2. 拟合初始 OLS 模型
3. 检查残差诊断
4. 检验异方差性、自相关性
5. 检查多重共线性（VIF）
6. 识别高影响力观测点
7. 若需要，改用稳健标准误重新拟合
8. 解读系数与推断结果
9. 在留出集或通过交叉验证进行验证

### 工作流 2：二元分类

1. 拟合逻辑回归（Logit）
2. 检查收敛性问题
3. 解读比值比
4. 计算边际效应
5. 评估分类性能（AUC、混淆矩阵）
6. 检查高影响力观测点
7. 与替代模型（Probit）比较
8. 在测试集上验证预测结果

### 工作流 3：计数数据分析

1. 拟合泊松回归
2. 检查过度离散
3. 若存在过度离散，改用负二项回归
4. 检查是否存在过多零值（可考虑 ZIP/ZINB）
5. 解读发生率比
6. 评估拟合优度
7. 通过 AIC 比较模型
8. 验证预测结果

### 工作流 4：时间序列预测

1. 绘制序列图，检查趋势/季节性
2. 检验平稳性（ADF、KPSS）
3. 若非平稳，进行差分
4. 从 ACF/PACF 中识别 p、q
5. 拟合 ARIMA 或 SARIMAX
6. 检查残差诊断（Ljung-Box）
7. 生成带置信区间的预测
8. 在测试集上评估预测准确度

## 参考文档

本技能包含详尽的参考文件，用于提供详细指导：

### references/linear_models.md
详细介绍线性回归模型，包括：
- OLS、WLS、GLS、GLSAR、分位数回归
- 混合效应模型
- 递归回归与滚动回归
- 全面的诊断（异方差性、自相关性、多重共线性）
- 影响力统计量与离群值检测
- 稳健标准误（HC、HAC、聚类）
- 假设检验与模型比较

### references/glm.md
广义线性模型完整指南：
- 所有分布族（二项分布、泊松分布、伽马分布等）
- 连接函数及各自的适用场景
- 模型拟合与解读
- 伪 R 方与拟合优度
- 诊断与残差分析
- 应用场景（逻辑回归、泊松回归、伽马回归）

### references/discrete_choice.md
离散结果模型全面指南：
- 二元模型（Logit、Probit）
- 多分类模型（MNLogit、条件 Logit）
- 计数模型（泊松、负二项、零膨胀、Hurdle）
- 有序模型
- 边际效应与解读
- 模型诊断与比较

### references/time_series.md
深入的时间序列分析指南：
- 单变量模型（AR、ARIMA、SARIMAX、指数平滑）
- 多变量模型（VAR、VARMAX、动态因子模型）
- 状态空间模型
- 平稳性检验与诊断
- 预测方法与评估
- 格兰杰因果检验、IRF、FEVD

### references/stats_diagnostics.md
全面的统计检验与诊断：
- 残差诊断（自相关性、异方差性、正态性）
- 影响力与离群值检测
- 假设检验（参数与非参数）
- 方差分析（ANOVA）与事后检验
- 多重比较校正
- 稳健协方差矩阵
- 功效分析与效应量

**何时查阅**：
- 需要详细的参数说明
- 在相似模型之间做选择
- 排查收敛或诊断方面的问题
- 理解特定的检验统计量
- 查找高级功能的代码示例

**搜索模式**：
```bash
# Find information about specific models
rg "Quantile Regression" references/

# Find diagnostic tests
rg "Breusch-Pagan" references/stats_diagnostics.md

# Find time series guidance
rg "SARIMAX" references/time_series.md
```

## 应当避免的常见陷阱

1. **忘记常数项**：除非确实不需要截距，否则始终使用 `sm.add_constant()`
2. **忽视假设**：检查残差、异方差性、自相关性
3. **结果类型与模型不匹配**：二元 → Logit/Probit，计数 → 泊松/负二项，
   而非 OLS
4. **未检查收敛性**：留意优化过程中的警告信息
5. **误读系数**：记住连接函数的影响（对数、logit 等）
6. **在存在过度离散时仍使用泊松模型**：检查离散程度，需要时改用负
   二项模型
7. **未使用稳健标准误**：当存在异方差性或聚类结构时
8. **过拟合**：相对样本量而言参数过多
9. **数据泄漏**：在测试数据上拟合，或使用了未来信息
10. **未验证预测结果**：应始终检查样本外表现
11. **比较非嵌套模型**：应使用 AIC/BIC，而非 LR 检验
12. **忽视高影响力观测点**：检查 Cook 距离与杠杆值
13. **多重检验**：在检验多个假设时应校正 p 值
14. **未对时间序列进行差分**：在非平稳数据上拟合 ARIMA
15. **混淆预测区间与置信区间**：预测区间更宽

## 获取帮助

如需详细文档与示例：
- 官方文档：https://www.statsmodels.org/stable/
- 用户指南：https://www.statsmodels.org/stable/user-guide.html
- 示例：https://www.statsmodels.org/stable/examples/index.html
- API 参考：https://www.statsmodels.org/stable/api.html
