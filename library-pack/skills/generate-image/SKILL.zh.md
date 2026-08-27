# 生成图像（Generate Image）

通过 OpenRouter 的 Image API 生成和编辑图像，该 API 用一种统一的请求格式对接 Gemini、Seedream、Recraft、
GPT-Image、Riverflow 以及大约三十个其他模型。

## 何时使用

**使用此技能生成**： 照片和写实图像、插画与艺术作品、概念图（concept art）、
演示文稿和海报视觉素材、徽标（logo）和矢量图标、图像编辑，以及基于参考图像的合成。

**改用 `scientific-schematics` 的场景：** 流程图、电路图、生物学通路图、
系统架构图、CONSORT 图，以及其他技术性示意图。

## API 密钥

生成图像需要 OpenRouter 密钥。脚本会按以下顺序解析该密钥：

1. `--api-key`
2. `OPENROUTER_API_KEY` 环境变量
3. `.env` 文件中的 `OPENROUTER_API_KEY=`，脚本会从工作目录向上逐级搜索，再搜索
   脚本自身所在目录

若上述均未找到，脚本会退出并给出配置说明。密钥获取地址：https://openrouter.ai/keys

`--list-models`、`--model-info` 和 `--dry-run` 均不需要密钥。

## 快速开始

```bash
# Generate
python scripts/generate_image.py "A beautiful sunset over mountains"

# Edit an existing image
python scripts/generate_image.py "Make the sky purple" -i photo.jpg -o edited.png
```

路径是相对于此技能所在目录的。输出文件默认名为 `generated_image.<ext>`，其中
扩展名遵循模型返回的媒体类型。运行结束后会打印本次请求的费用。

**然后要查看图像**。 在将图像用于任何用途之前，先把文件读回来检查：构图、
宽高比，以及图中任何文字，都是模型容易在悄无声息间出错的地方。

## 选择模型

默认：`google/gemini-3.1-flash-image`。

| 需求 | 模型 |
| --- | --- |
| 综合质量、对提示词的遵循度 | `google/gemini-3.1-flash-image` |
| 最高档次的 Gemini | `google/gemini-3-pro-image` |
| 廉价迭代 | `google/gemini-3.1-flash-lite-image`（仅 1K）、`openai/gpt-image-1-mini` |
| 照片级真实感控制、可复现的种子 | `bytedance-seed/seedream-4.5` |
| 单次请求生成多张图像 | `bytedance-seed/seedream-4.5`、`openai/gpt-image-2`（最多 10 张） |
| 矢量 / SVG 输出 | `recraft/recraft-v4.1-vector` |
| 透明背景 | `openai/gpt-image-1` 配合 `--background transparent` |
| 图像内文字清晰可读 | `recraft/recraft-v4.1`、`sourceful/riverflow-v2.5-pro` —— 见下方注意事项 |

`references/models.md` 收录了完整目录，包含各模型的参数、允许取值和价格。实时列表是权威且免费的：

```bash
python scripts/generate_image.py --list-models            # every model and its allowed values
python scripts/generate_image.py --list-models gemini     # filtered by substring
python scripts/generate_image.py --model-info openai/gpt-image-1   # one model, plus pricing
```

## 参数支持因模型而异

这是最需要弄对的一点。各模型宣称支持的参数集**及其允许取值**均不相同，
发送某个模型不支持的参数会被拒绝，而不是被忽略。

脚本会在花费任何费用之前对照实时目录检查请求，因此错误的参数会在不到一秒内
在本地失败，并打印出合法取值：

```console
$ python scripts/generate_image.py "abstract pattern" -m openai/gpt-image-2 --background transparent
Error: Request rejected before billing (1 problem):
  - background=transparent is not allowed; this model accepts: auto, opaque
```

大致指南——但请以检查结果为准，因为目录会不断变动：

- `--resolution` —— Gemini、Seedream、Riverflow、Krea、Grok。各档次不同：`512` 仅在 Gemini
  3.1 Flash 上可用，`4K` 在 Gemini 3 Pro / Seedream / Riverflow 上可用，而 **仅有 `1K`** 在
  `gemini-3.1-flash-lite-image` 和 Krea 系列模型上可用。
- `--output-format` —— 仅 Riverflow 2.5（`png`、`jpeg`、`webp`；`fast` 变体仅支持 `jpeg`
  一种）。Gemini、OpenAI、Seedream 和 Recraft 都自行选择其容器格式。
- `--quality`、`--background`、`--output-compression` —— OpenAI 系列，以及
  Riverflow 2.5 上的 `--background`。**`--background transparent` 在 `gpt-image-2` 或
  `gpt-5.4-image-2` 上不可用**——请使用 `gpt-image-1`、`gpt-image-1-mini`、`gpt-5-image` 或 `gpt-5-image-mini`。
- `--seed` —— Seedream 和 Krea。Gemini 和 OpenAI 不支持。
- `--aspect-ratio` —— 几乎所有模型都支持，但枚举值差异很大：`gpt-image-1` 仅接受
  `1:1`、`3:2`、`2:3`、`auto`，而 `gpt-5-image*` 完全不接受此参数。
- `--n` —— 每个模型有各自上限：Gemini、Riverflow、MAI 和 Grok 为 1，Recraft 为 6，Seedream
  和 OpenAI 为 10。Krea 系列模型则直接拒绝此参数。

传入 `--dry-run` 可验证并打印出确切的请求体，而不会生成图像或产生费用。
`--no-preflight` 会跳过该检查，让 API 自身来判定。

## 撰写提示词

提示词质量对输出质量的影响超过模型选择本身。请用一句话分别说明以下各项：

1. **主体（Subject）**——画面中有什么，占多大比例。例如："A single pipette tip above a 96-well plate."
2. **媒介与风格（Medium and style）**——照片、水彩、3D 渲染、扁平矢量、科学插图。
3. **光照与色调（Lighting and palette）**——例如 "soft diffuse lighting, cool blue and white palette."
4. **构图（Composition）**——例如 "wide shot, subject left of centre, empty space on the right for a title."
5. **应避免的内容（What to avoid）**——例如 "no text, no labels, no watermark."

在需要放置标题或说明文字的位置要求留白，是海报和幻灯片场景中最实用的一条构图指令。

低成本迭代的方法：先在 `gemini-3.1-flash-lite-image` 上打草稿，确定好措辞后
再用真正想用的模型重新生成。若想在已有结果基础上微调而非重新开始，可将上一次的
输出作为参考图像（`-i out.png`）传入，只描述需要修改的部分。

## 编辑与参考图像

`-i/--input` 可重复传入，支持本地路径、HTTP(S) URL 或 data URL。本地文件会被
进行 base64 编码，并作为 `input_references` 发送。

```bash
# Single-image edit
python scripts/generate_image.py "Add sunglasses to the person" -i portrait.png

# Composite several references
python scripts/generate_image.py "Blend these two styles" -i style_a.png -i style_b.jpg -o blend.png

# Reference an image already on the web
python scripts/generate_image.py "Restyle as a watercolor" -i https://example.com/photo.jpg
```

各模型的参考图像数量上限不同：OpenAI 为 16，Gemini 和 Seedream 为 14，`riverflow-v2*-pro` 为 10，
`gemini-2.5-flash-image` 和 Grok 为 3，Recraft、MAI 和 Krea 为 1。支持的本地格式：PNG、
JPEG、GIF、WebP。Riverflow v2 在输出费用之外，每张参考图像额外收取 $0.20。

## 实用示例

以下 `-o` 路径均为脚本创建的目标文件，而非随此技能一并提供的文件。

```bash
# Wide hero image for a poster, with space reserved for the title
python scripts/generate_image.py \
  "Laboratory with modern equipment, photorealistic, well-lit, wide shot, \
   equipment on the left, empty wall on the right, no text" \
  --aspect-ratio 21:9 --resolution 2K -o poster/hero.png

# Conceptual illustration for a manuscript — illustrative, never presented as data
python scripts/generate_image.py \
  "Stylised illustration of immune cells surrounding a tumour cell, scientific illustration, \
   cool palette, no text" \
  --resolution 2K -o figures/immunotherapy_concept.png

# Vector logo
python scripts/generate_image.py \
  "Minimal geometric fox logo, two colors" \
  -m recraft/recraft-v4.1-vector -o assets/logo.svg

# Slide background with a transparent alpha channel
python scripts/generate_image.py \
  "Abstract molecular pattern, subtle, blue and white, no text" \
  -m openai/gpt-image-1 --background transparent -o slides/bg.png

# Four variations in one request
python scripts/generate_image.py \
  "Stylized neuron network illustration" \
  -m bytedance-seed/seedream-4.5 --n 4 -o variations.png
# -> variations_1.png ... variations_4.png

# Reproducible output
python scripts/generate_image.py "A cat astronaut" \
  -m bytedance-seed/seedream-4.5 --seed 42

# Check a request costs nothing to get wrong
python scripts/generate_image.py "A cat astronaut" --resolution 4K --dry-run
```

## 脚本参数

| 标志 | 作用 |
| --- | --- |
| `prompt` | 图像描述，或要应用的编辑内容（除非使用 `--list-models` / `--model-info`，否则为必填） |
| `-m`, `--model` | 模型标识（默认 `google/gemini-3.1-flash-image`） |
| `-o`, `--output` | 输出路径；扩展名默认取自返回的媒体类型 |
| `-i`, `--input` | 参考图像——路径、URL 或 data URL。可重复传入 |
| `--n` | 每次请求生成的图像数量，受模型上限约束 |
| `--aspect-ratio` | `1:1`、`16:9`、`9:16`、`4:3`、`3:2`、`21:9` 等——枚举值因模型而异 |
| `--resolution` | `512`、`1K`、`2K`、`4K`——档次因模型而异 |
| `--quality` | `auto`、`low`、`medium`、`high`（OpenAI） |
| `--output-format` | `png`、`jpeg`、`webp`（Riverflow 2.5） |
| `--background` | `auto`、`transparent`、`opaque` |
| `--output-compression` | 0–100，OpenAI 系列模型 |
| `--seed` | 在支持的情况下用于确定性输出 |
| `--api-key` | 覆盖环境变量和 `.env` |
| `--timeout` | 请求超时时间，单位秒（默认 300） |
| `--retries` | 针对速率限制和 5xx 响应的重试次数（默认 2） |
| `--no-preflight` | 跳过计费请求之前的免费能力检查 |
| `--dry-run` | 验证并打印请求，然后退出而不生成图像 |
| `--list-models` | 打印目录及允许取值，可选按条件过滤，然后退出 |
| `--model-info` | 打印单个模型的允许取值和定价，然后退出 |

没有 `--size` 这个参数：目录中没有任何模型接受 `size` 参数。请使用
`--aspect-ratio` 和 `--resolution` 来控制输出的形状。

## API 格式

若不通过脚本而直接发起请求：

```bash
curl -s https://openrouter.ai/api/v1/images \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "google/gemini-3.1-flash-image",
    "prompt": "A red bicycle against a white wall",
    "aspect_ratio": "16:9"
  }'
```

响应：

```json
{
  "created": 1748372400,
  "data": [{ "b64_json": "<base64>", "media_type": "image/png" }],
  "usage": {
    "prompt_tokens": 4,
    "completion_tokens": 1120,
    "total_tokens": 1124,
    "cost": 0.0672,
    "completion_tokens_details": { "image_tokens": 1120 }
  }
}
```

`b64_json` 是原始 base64 编码，**不是** data URL。`media_type` 反映了真实格式，因此在
命名文件时应遵循该字段——矢量模型返回 `image/svg+xml`，而 `gemini-3.1-flash-lite-image` 返回的是
JPEG 而非 PNG。

流式传输（`"stream": true`）会发出 `image_generation.partial_image`、`image_generation.completed`
和 `error` 事件，最终以 `data: [DONE]` 结束。只有 OpenAI 系列模型支持流式传输，且
随附脚本并未使用该功能。

计费是全有或全无的：一次生成要么完成并全额计费，要么失败且不计费——因此
被拒绝的参数只会浪费时间，不会产生费用。流式预览帧不会单独计费。在使用自带密钥（bring-your-own-key）的账户上，
`usage.cost` 显示为 `0`，真实金额记录在 `cost_details.upstream_inference_cost` 中；脚本会
报告该数值，而不会声称本次运行是免费的。

## 费用

按图计费的模型价格是可预测的：Seedream $0.04，Recraft v4.1 $0.035（矢量版 $0.08，专业版 $0.21），
Riverflow 2.5 快速版 $0.019、专业版 $0.13–0.17，Grok $0.05–0.07。

Gemini、OpenAI 和 MAI 按输出 token 计费，其费用会随分辨率变化——4K 图像的费用约为 1K 图像的
十六倍。实测数据：一次 1K 分辨率的 `gemini-3.1-flash-lite-image` 渲染消耗 1120
输出 token，费用 $0.034。同样尺寸下，`gemini-3.1-flash-image` 是其两倍，
`gemini-3-pro-image` 是其四倍。建议先用廉价模型以低分辨率打草稿，只在需要大尺寸时才付费。

## 注意事项与告诫

- **模型在处理文字上不可信赖**。 生成图像内的文字往往拼写错误、乱码或凭空捏造。
  应要求 "no text"，并在 LaTeX、PowerPoint 或 HTML 中叠加真实文字——或者
  在标签是关键需求时使用 `scientific-schematics`。
- **生成的图像只是插图，绝不是证据**。 它不代表任何被实际测量出来的东西。
  切勿将其呈现为显微成像、影像、凝胶电泳或仪器输出，切勿让它替代报告实际结果的
  图表，并应在图注中标注其为插图。Nature 和 Science 均要求披露生成式 AI 图像，
  且多家期刊禁止在明确标注为概念图之外使用此类图像——提交前请核查目标期刊的规定。
- 生成图像是付费 API 调用。在打磨措辞阶段应优先使用廉价模型和低分辨率。
- 生成过程大约需要 5–60 秒，具体取决于模型和分辨率。
- 参考图像会被上传至 OpenRouter。请勿发送未公开或敏感数据、患者
  图像，或任何处于保密期（embargo）的内容。
- 切勿将 API 密钥硬编码。应将其保存在环境变量或已被忽略（ignored）的 `.env` 文件中。
- 编辑时应给出具体提示："change the sky to sunset colours" 比 "edit the sky" 更有效。
- 拒绝请求会以提及内容政策的 HTTP 400 或 403 形式返回，而不是生成一张劣质图像。请改述提示词——
  临床和解剖学主题触发内容审核的频率往往高于其本身应有的程度。
- 速率限制和 5xx 响应会自动重试；4xx 是终态，因为需要修改的是请求本身。

## 相关技能

- `scientific-schematics` —— 技术性示意图、流程图、电路图、通路图
- `scientific-slides` —— 内嵌生成视觉素材的演示文稿
- `latex-posters` —— 内嵌主图（hero image）的海报
