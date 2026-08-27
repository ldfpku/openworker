# SymPy - Python 中的符号数学（Symbolic Mathematics）

## 概述

SymPy 是一个用于符号数学计算的 Python 库，它使用数学符号而非数值近似来实现精确计算。本技能提供了使用 SymPy 进行符号代数运算、微积分、线性代数、方程求解、物理计算及代码生成的全面指导。

## 安装

已针对 **SymPy 1.14.0**（稳定版；2025 年 4 月）进行测试。需要 **Python 3.9+**。

```bash
# Install SymPy using uv
uv pip install "sympy>=1.14"

# Optional: for lambdify and plotting examples
uv pip install numpy scipy matplotlib
```

检查版本：

```python
import sympy
print(sympy.__version__)
```

## 何时使用本技能

在以下情形使用本技能：
- 以符号方式求解方程（代数方程、微分方程、方程组）
- 执行微积分运算（导数、积分、极限、级数）
- 操作与化简代数表达式
- 以符号方式处理矩阵及线性代数
- 进行物理计算（力学、量子力学、矢量分析）
- 数论计算（素数、因式分解、模运算）
- 几何计算（二维/三维几何、解析几何）
- 将数学表达式转换为可执行代码（Python、C、Fortran）
- 生成 LaTeX 或其他格式化的数学输出
- 需要精确的数学结果（例如 `sqrt(2)` 而非 `1.414...`）

## 核心能力

七个能力领域记录于
[references/core_capabilities.md](references/core_capabilities.md)：

1. **符号计算基础** —— 符号（symbol）、表达式、化简、代换。
2. **微积分** —— 求导、积分、极限、级数。
3. **方程求解** —— `solve`、`solveset`、线性与非线性方程组、常微分方程（ODE）。
4. **矩阵与线性代数** —— 参见
   [references/matrices-linear-algebra.md](references/matrices-linear-algebra.md)。
5. **物理与力学** —— 参见
   [references/physics-mechanics.md](references/physics-mechanics.md)。
6. **高等数学** —— 参见
   [references/advanced-topics.md](references/advanced-topics.md)。
7. **代码生成与输出** —— 参见
   [references/code-generation-printing.md](references/code-generation-printing.md)。

关于前三项更深入的讲解见
[references/core-capabilities.md](references/core-capabilities.md)。

## 使用 SymPy 的最佳实践

### 1. 始终先定义符号

```python
from sympy import symbols
x, y, z = symbols('x y z')
# Now x, y, z can be used in expressions
```

### 2. 使用假设条件（Assumptions）以获得更好的化简效果

```python
x = symbols('x', positive=True, real=True)
sqrt(x**2)  # Returns x (not Abs(x)) due to positive assumption
```

常用的假设条件：`real`、`positive`、`negative`、`integer`、`rational`、`complex`、`even`、`odd`

### 3. 使用精确算术

```python
from sympy import Rational, S
# Correct (exact):
expr = Rational(1, 2) * x
expr = S(1)/2 * x

# Incorrect (floating-point):
expr = 0.5 * x  # Creates approximate value
```

### 4. 需要时进行数值求值

```python
from sympy import pi, sqrt
result = sqrt(8) + pi
result.evalf()    # 5.96371554103586
result.evalf(50)  # 50 digits of precision
```

### 5. 为提升性能而转换为 NumPy

```python
# Slow for many evaluations:
for x_val in range(1000):
    result = expr.subs(x, x_val).evalf()

# Fast:
f = lambdify(x, expr, 'numpy')
results = f(np.arange(1000))
```

### 6. 使用恰当的求解器

- `solveset`：代数方程（首选）
- `linsolve`：线性方程组
- `nonlinsolve`：非线性方程组
- `dsolve`：微分方程
- `solve`：通用求解器（历史遗留，但较为灵活）

## 参考文件结构

本技能针对不同能力使用了模块化的参考文件：

1. **`core-capabilities.md`**：符号、代数、微积分、化简、方程求解
   - 使用场景：基础符号计算、微积分或方程求解

2. **`matrices-linear-algebra.md`**：矩阵运算、特征值、线性方程组
   - 使用场景：处理矩阵或线性代数问题

3. **`physics-mechanics.md`**：经典力学、量子力学、矢量、单位
   - 使用场景：物理计算或力学问题

4. **`advanced-topics.md`**：几何、数论、组合数学、逻辑、统计
   - 使用场景：超出基础代数与微积分范围的高等数学主题

5. **`code-generation-printing.md`**：lambdify、代码生成（codegen）、LaTeX 输出、打印
   - 使用场景：将表达式转换为代码，或生成格式化输出

## 常见用例模式

### 模式一：求解并验证

```python
from sympy import symbols, solve, simplify
x = symbols('x')

# Solve equation
equation = x**2 - 5*x + 6
solutions = solve(equation, x)  # [2, 3]

# Verify solutions
for sol in solutions:
    result = simplify(equation.subs(x, sol))
    assert result == 0
```

### 模式二：符号到数值的流水线

```python
# 1. Define symbolic problem
x, y = symbols('x y')
expr = sin(x) + cos(y)

# 2. Manipulate symbolically
simplified = simplify(expr)
derivative = diff(simplified, x)

# 3. Convert to numerical function
f = lambdify((x, y), derivative, 'numpy')

# 4. Evaluate numerically
results = f(x_data, y_data)
```

### 模式三：记录数学计算结果

```python
# Compute result symbolically
integral_expr = Integral(x**2, (x, 0, 1))
result = integral_expr.doit()

# Generate documentation
print(f"LaTeX: {latex(integral_expr)} = {latex(result)}")
print(f"Pretty: {pretty(integral_expr)} = {pretty(result)}")
print(f"Numerical: {result.evalf()}")
```

## 与科研工作流的集成

### 与 NumPy 结合

```python
import numpy as np
from sympy import symbols, lambdify

x = symbols('x')
expr = x**2 + 2*x + 1

f = lambdify(x, expr, 'numpy')
x_array = np.linspace(-5, 5, 100)
y_array = f(x_array)
```

### 与 Matplotlib 结合

```python
import matplotlib.pyplot as plt
import numpy as np
from sympy import symbols, lambdify, sin

x = symbols('x')
expr = sin(x) / x

f = lambdify(x, expr, 'numpy')
x_vals = np.linspace(-10, 10, 1000)
y_vals = f(x_vals)

plt.plot(x_vals, y_vals)
plt.show()
```

### 与 SciPy 结合

```python
from scipy.optimize import fsolve
from sympy import symbols, lambdify

# Define equation symbolically
x = symbols('x')
equation = x**3 - 2*x - 5

# Convert to numerical function
f = lambdify(x, equation, 'numpy')

# Solve numerically with initial guess
solution = fsolve(f, 2)
```

## 快速参考：最常用的函数

```python
# Symbols
from sympy import symbols, Symbol
x, y = symbols('x y')

# Basic operations
from sympy import simplify, expand, factor, collect, cancel
from sympy import sqrt, exp, log, sin, cos, tan, pi, E, I, oo

# Calculus
from sympy import diff, integrate, limit, series, Derivative, Integral

# Solving
from sympy import solve, solveset, linsolve, nonlinsolve, dsolve

# Matrices
from sympy import Matrix, eye, zeros, ones, diag

# Logic and sets
from sympy import And, Or, Not, Implies, FiniteSet, Interval, Union

# Output
from sympy import latex, pprint, lambdify, init_printing

# Utilities
from sympy import evalf, N, nsimplify
```

## 入门示例

### 示例一：求解二次方程
```python
from sympy import symbols, solve, sqrt
x = symbols('x')
solution = solve(x**2 - 5*x + 6, x)
# [2, 3]
```

### 示例二：计算导数
```python
from sympy import symbols, diff, sin
x = symbols('x')
f = sin(x**2)
df_dx = diff(f, x)
# 2*x*cos(x**2)
```

### 示例三：求积分
```python
from sympy import symbols, integrate, exp
x = symbols('x')
integral = integrate(x * exp(-x**2), (x, 0, oo))
# 1/2
```

### 示例四：矩阵特征值
```python
from sympy import Matrix
M = Matrix([[1, 2], [2, 1]])
eigenvals = M.eigenvals()
# {3: 1, -1: 1}
```

### 示例五：生成 Python 函数
```python
from sympy import symbols, lambdify
import numpy as np
x = symbols('x')
expr = x**2 + 2*x + 1
f = lambdify(x, expr, 'numpy')
f(np.array([1, 2, 3]))
# array([ 4,  9, 16])
```

## 常见问题排查

1. **"NameError: name 'x' is not defined"**
   - 解决方案：使用前始终先用 `symbols()` 定义符号

2. **数值结果与预期不符**
   - 问题所在：使用了像 `0.5` 这样的浮点数，而不是 `Rational(1, 2)`
   - 解决方案：使用 `Rational()` 或 `S()` 以实现精确算术

3. **循环中性能缓慢**
   - 问题所在：反复使用 `subs()` 和 `evalf()`
   - 解决方案：使用 `lambdify()` 创建一个快速的数值函数

4. **"Can't solve this equation"（无法求解该方程）**
   - 尝试不同的求解器：`solve`、`solveset`、`nsolve`（数值求解）
   - 检查该方程是否可以代数求解
   - 如果不存在封闭形式的解，则使用数值方法

5. **化简结果不如预期**
   - 尝试不同的化简函数：`simplify`、`factor`、`expand`、`trigsimp`
   - 为符号添加假设条件（例如 `positive=True`）
   - 使用 `simplify(expr, force=True)` 进行更激进的化简

## 更多资源

- 官方文档：https://docs.sympy.org/
- 教程：https://docs.sympy.org/latest/tutorials/intro-tutorial/index.html
- API 参考：https://docs.sympy.org/latest/reference/index.html
- 示例：https://github.com/sympy/sympy/tree/master/examples
