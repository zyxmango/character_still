# 古装人物剧照智能生成平台

> 一条面向批量生产的「人设 → 提示词 → 剧照 → 修图 → 质检 → 入库」流水线。
> 本地 **Ollama** 生成中英双语提示词，本地 **ComfyUI（FLUX + LoRA）** 出图，**千问 Edit 2509** 做条件修图，云端 **qwen-vl-plus** 做质量评分。

- 提示词与出图全部走本地 GPU，无需为每次生图付费
- 8 个确定性工具函数 + 异步任务队列，适合成百上千张的批量出图
- WebSocket 实时进度、断点续传、失败重试、串行调度避免显存冲突
- 提示词规则集中在一个 Markdown 的 YAML 配置块里，改风格不用改代码

---

## 目录

- [1. 功能概览](#1-功能概览)
- [2. 技术栈](#2-技术栈)
- [3. 项目结构](#3-项目结构)
- [4. 前置准备（必读）](#4-前置准备必读)
- [5. 部署与启动](#5-部署与启动)
- [6. 使用流程](#6-使用流程)
- [7. 修改人物剧照风格：要换哪些东西](#7-修改人物剧照风格要换哪些东西)
- [8. 配置项](#8-配置项)
- [9. API 摘要](#9-api-摘要)
- [10. 常见问题](#10-常见问题)

---

## 1. 功能概览

| 模块 | 说明 |
|------|------|
| 提示词生成 | 按风格 / 身份 / 年龄段 / 性别 / 颜色 / 特殊特征批量生成中英文双语提示词（JSON） |
| 剧照生成 | 调用 ComfyUI 的 FLUX 工作流批量出图，按任务 ID 归档，支持断点续传与强制重出 |
| 条件修图 | 千问 Edit 2509：原图 + 中文指令生成新图，支持多图批量、每图独立指令、覆盖原图 |
| 质量评估 | qwen-vl-plus 按人物完整性 / 服饰准确性 / 颜色匹配度 / 构图 / 风格一致性 5 维打分，低分标记 `needs_regen` |
| 全流程 | 提示词 → 出图 →（可选）修图一键执行 |
| 画廊与导出 | 按文件夹浏览、勾选图片，导出打标 Excel + 入库 SQL |
| 自定义风格 | 自然语言描述风格 → LLM 生成 StyleConfig → 保存后可直接复用 |
| 系统监控 | GPU、任务队列、Ollama / ComfyUI / DashScope 健康状态、磁盘产物统计 |

**架构链路**

```
表单 / 批量参数
      │
      ▼
FastAPI（REST + WebSocket）+ 串行任务队列
      │
      ├─ T→T  Ollama qwen2.5:14b ──→ output/prompts/*.json
      ├─ T→I  ComfyUI FLUX + LoRA ─→ output/stills/<task_id>/*.png
      ├─ I+T→I 千问 Edit 2509 ─────→ output/edited/<task_id>/*.png
      └─ I→T  qwen-vl-plus ────────→ 5 维评分报告
```

---

## 2. 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.10+、FastAPI、Uvicorn、Pydantic、Requests、WebSockets |
| 前端 | Vue 3（`<script setup>`）、Element Plus、Pinia、Vue Router、Vite 5、axios |
| 本地 LLM | Ollama + qwen2.5:14b（可降级 qwen2.5:7b / qwen3:32b） |
| 文生图 | ComfyUI + FLUX.1-dev（fp8）+ 古风 LoRA |
| 修图 | ComfyUI + Qwen-Image-Edit-2509（fp8） |
| 质量评估 | 阿里云百炼 qwen-vl-plus（云端 API） |
| 存储 | 本地文件系统 + SQLite（任务队列 / 会话历史） |

---

## 3. 项目结构

```
character_still/
├── backend/
│   ├── server.py                  # FastAPI 入口：REST + WebSocket + 前端静态文件
│   ├── tools.py                   # 8 个确定性工具函数（生成 / 出图 / 修图 / 评估 / 导出）
│   ├── main_end.py                # Ollama 提示词生成引擎（双语输出 + 约束校验）
│   ├── comfyui_client.py          # ComfyUI 客户端（提交工作流、轮询、下载图片）
│   ├── task_queue.py              # 串行任务队列（SQLite 持久化 + 断点续传）
│   ├── style_manager.py           # 自定义风格（LLM 生成 StyleConfig）
│   ├── prompt_loader.py           # 解析 prompt_engineering.md 的 YAML 配置块
│   ├── prompts/
│   │   └── prompt_engineering.md  # ★ 提示词约束中心（风格 / 身份 / 颜色 / 全局规则）
│   ├── config.py                  # 路径、服务地址、工作流节点 ID、模型参数
│   ├── requirements.txt
│   ├── .env.example               # 环境变量清单（不是自动加载文件，见 4.3）
│   ├── static/                    # 前端构建产物（npm run build 输出到这里）
│   └── tests/test_pipeline.py
├── frontend/
│   ├── src/views/                 # 提示词 / 剧照 / 修图 / 全流程 / 任务 / 画廊 / 监控 / 工程配置
│   ├── src/api/index.js
│   ├── package.json
│   └── vite.config.js
├── FLUX(文生图）-短剧项目-API-agent(test).json          # ★ 文生图工作流（API 格式）
├── 服装迁移-千问Edit2509图像编辑 (2)-API-agent-test.json # ★ 修图工作流（API 格式）
├── output/                        # 运行产物（已被 .gitignore 忽略）
│   ├── prompts/  stills/  edited/  export/  config/  logs/
│   └── tasks.db
└── README.md
```

> 根目录另有两份 ComfyUI **UI 格式**工作流（不带 `-API` 后缀），仅用于在 ComfyUI 界面里查看和编辑；后端实际调用的是 `-API-agent-test.json` 这类 API 格式文件。

---

## 4. 前置准备（必读）

### 4.1 硬件与系统

| 项目 | 要求 |
|------|------|
| GPU | NVIDIA 显卡，显存 **≥ 16GB**，建议 24GB（RTX 3090 / 4090） |
| 驱动 | 已安装可用的 NVIDIA 驱动与 CUDA 环境（ComfyUI 能正常出图即可） |
| 系统 | Windows 10/11 或 Linux |
| Python | 3.10 / 3.11（推荐 conda 管理） |
| Node.js | 18 及以上（仅前端开发/构建需要） |
| Git | 用于克隆仓库 |

> FLUX 与 Qwen-Image-Edit 不要同时塞进显存。项目默认 `MAX_CONCURRENT_TASKS=1`，GPU 任务串行执行。

### 4.2 需要安装并启动的服务

#### （1）Ollama —— 生成提示词

```bash
# 安装：https://ollama.com/download
ollama pull qwen2.5:14b
ollama serve          # 默认监听 http://localhost:11434
```

- 显存不足时可改用 `qwen2.5:7b`，并在环境变量里改 `OLLAMA_MODEL`
- 服务地址不是默认值时改 `OLLAMA_URL`

#### （2）ComfyUI —— 出图与修图

在 `http://127.0.0.1:8188` 启动 ComfyUI，并准备以下模型文件。**文件名必须与工作流中完全一致**（含大小写、后缀）：

| 用途 | 文件名 | 放到 ComfyUI 的目录 |
|------|--------|----------------------|
| FLUX 主模型 | `flux1-dev.safetensors` | `ComfyUI/models/unet/` |
| FLUX 文本编码器 1 | `clip_l.safetensors` | `ComfyUI/models/clip/` |
| FLUX 文本编码器 2 | `t5xxl_fp16.safetensors` | `ComfyUI/models/clip/` |
| FLUX VAE | `ae.safetensors` | `ComfyUI/models/vae/` |
| 古风画风 LoRA | `F.1-古风小说推文（堪比niji）_v2.0.safetensors` | `ComfyUI/models/loras/` |
| 修图主模型 | `qwen_image_edit_2509_fp8_e4m3fn.safetensors` | `ComfyUI/models/unet/` |
| 修图文本编码器 | `qwen_2.5_vl_7b_fp8_scaled.safetensors` | `ComfyUI/models/clip/` |
| 修图 VAE | `qwen_image_vae.safetensors` | `ComfyUI/models/vae/` |

补充说明：

- FLUX.1-dev 可从 `black-forest-labs/FLUX.1-dev` 获取，fp8 版本可从 Comfy-Org 的打包仓库获取
- Qwen-Image-Edit-2509 可从 `Qwen/Qwen-Image-Edit-2509` 获取
- 古风 LoRA 为第三方模型，请自行下载并遵守其作者的使用条款
- 修图工作流还用到一个自定义节点：`TextEncodeQwenImageEditPlus_lrzjason`。用 ComfyUI-Manager 搜索安装对应插件，或按 ComfyUI 打开工作流时的红色节点提示补齐
- 建议安装 **ComfyUI-Manager**，便于补节点和查缺模型

#### （3）阿里云百炼 API Key（可选）

只用于「质量评估」。不配置时其余功能正常，`/api/evaluate` 会返回明确错误。

1. 注册 / 登录 <https://bailian.console.aliyun.com/>
2. 模型广场 → API-KEY 管理 → 创建
3. 记住 Key，按 4.3 设置环境变量 `DASHSCOPE_API_KEY`

### 4.3 Python 与前端依赖

```bash
conda create -n character_agent python=3.11 -y
conda activate character_agent

# 后端依赖
pip install -r backend/requirements.txt

# 导出 Excel / SQL 需要（requirements 未包含）
pip install pandas openpyxl

# 前端依赖
cd frontend
npm install
```

### 4.4 环境变量（重要）

`backend/config.py` **直接读取操作系统环境变量，不会自动加载 `.env` 文件**。`backend/.env.example` 只是变量清单模板，请照它在启动前设置环境变量。

Windows PowerShell 示例：

```powershell
$env:DASHSCOPE_API_KEY="sk-你的Key"
$env:OLLAMA_URL="http://localhost:11434"
$env:OLLAMA_MODEL="qwen2.5:14b"
$env:COMFYUI_URL="http://127.0.0.1:8188"
$env:SERVER_PORT="8000"
$env:MAX_CONCURRENT_TASKS="1"
```

Linux / macOS 示例：

```bash
export DASHSCOPE_API_KEY="sk-你的Key"
export OLLAMA_MODEL="qwen2.5:14b"
export MAX_CONCURRENT_TASKS=1
```

> 每次新开终端都要重新设置；想长期生效可写入系统环境变量，或自行用 `python-dotenv` / 启动脚本加载 `.env`。

### 4.5 工作流文件

仓库根目录已包含可用的 API 格式工作流：

- 文生图：`FLUX(文生图）-短剧项目-API-agent(test).json`
- 修图：`服装迁移-千问Edit2509图像编辑 (2)-API-agent-test.json`

`backend/config.py` 里的默认值就指向这两个文件。如果你把文件改名或换位置，需要同步修改 `T2I_WORKFLOW` / `EDIT_WORKFLOW` 环境变量或 `config.py`。

---

## 5. 部署与启动

### 5.1 开发模式（前后端分离，推荐调试用）

**终端 1：后端**

```bash
conda activate character_agent
cd backend
python server.py
# 监听 http://127.0.0.1:8000
```

**终端 2：前端**

```bash
cd frontend
npm run dev
# 打开 http://localhost:5173
```

Vite 已配置代理：`/api`、`/ws`、`/files` 都会转发到 `http://127.0.0.1:8000`。

> Windows 上如果 conda 环境激活后找不到 Node.js：
> `$env:PATH = "C:\Program Files\nodejs;$env:PATH"`

### 5.2 生产模式（前端打包进后端，单端口）

```bash
# 1. 构建前端，产物自动输出到 backend/static/
cd frontend
npm run build

# 2. 启动后端（同时托管前端页面）
cd ../backend
python server.py
```

访问 `http://127.0.0.1:8000` 即可，前后端同源，无需再开 5173。

### 5.3 Docker 部署

Docker 镜像只包含后端与前端静态文件；Ollama 和 ComfyUI 仍建议跑在宿主机并使用 GPU。

```bash
# 先构建前端（Dockerfile 不会帮你构建）
cd frontend && npm run build && cd ..

# 再启动容器
cd backend
docker compose up -d --build
```

- 容器内通过 `host.docker.internal:11434` / `host.docker.internal:8188` 访问宿主机服务
- `output/` 与 `static/` 已挂载为数据卷
- `docker-compose.yml` 中的 `OLLAMA_MODEL` 默认是 `qwen3:32b`，如果你只下载了 `qwen2.5:14b`，请改成一致
- 容器内部不适合直接跑 ComfyUI（显存与驱动透传复杂），本项目的定位是「ComfyUI 在宿主机，Web 服务可容器化」

### 5.4 健康检查

```bash
curl http://127.0.0.1:8000/health
# {"server":"ok","ollama":"ok","comfyui":"ok"}
```

| 服务 | 默认地址 |
|------|----------|
| Web / API | `http://127.0.0.1:8000` |
| 前端开发服务器 | `http://localhost:5173` |
| Ollama | `http://localhost:11434` |
| ComfyUI | `http://127.0.0.1:8188` |

---

## 6. 使用流程

1. **生成提示词**：在「提示词」页选择风格、身份、年龄段、性别、数量、颜色等，生成 `output/prompts/*.json`
2. **生成剧照**：在「剧照」页选择提示词文件批量出图；同一任务重复执行会跳过已存在图片（断点续传）
3. **条件修图**（可选）：在「修图」页选图并填写中文指令，例如「把背景换成纯白，保持全身构图」
4. **质量评估**（可选）：在「画廊」勾选图片 → 质量评估，低分图会提示重出
5. **筛选导出**：勾选满意图片 → 导出打标 Excel + 入库 SQL 到 `output/export/`
6. **全流程**：想一步到位时直接用「全流程」页，自动串起提示词 → 出图 →（可选）修图

任务进度通过 WebSocket `/ws/tasks` 实时推送；断线后前端会自动重连。

---

## 7. 修改人物剧照风格：要换哪些东西

出图风格由 **三层** 共同决定。只改文字提示词不会改变画风，只换 LoRA 也改不了服饰和气质规则，通常需要按需组合。

| 层次 | 控制什么 | 要改的位置 |
|------|----------|-------------|
| ① 提示词层 | 气质、服饰、配色、姿势、光影、背景、质量词 | `backend/prompts/prompt_engineering.md` 里的 YAML 块（或前端「工程」页） |
| ② 画风层 | 二次元 / 写实 / 厚涂 / 水墨等整体笔触 | ComfyUI 的 **LoRA 文件** + 工作流里的 LoRA 节点 |
| ③ 基座层 | 底层生成模型能力 | ComfyUI 的 FLUX / Qwen Edit 模型文件 + 工作流加载节点 |

### 7.1 提示词层：改 `prompt_engineering.md`（不是独立 `.yaml` 文件）

提示词配置不是散落的 yaml 文件，而是集中在一个 Markdown 文档内的多个 `yaml` 代码块：

```
backend/prompts/prompt_engineering.md
```

| 区块 | 主要作用 |
|------|----------|
| 一、全局设定 | 世界观、服饰专家人设、固定背景与构图、质量词、鞋履规则、硬性要求、输出字段 |
| 二、数据库颜色 | 服装主色与辅色（生成与导出校验共用） |
| 三、身份设定 | 贵族 / 仙人 / 侠客等身份的特征、禁令、允许元素、时代 |
| 四、特殊特征 | 轮椅、独眼、孕妇等可叠加特征 |
| 五、风格预设 | **风格的核心**：描述、气质关键词、偏好颜色、姿势、光影、细节 |
| 六、面部特征词池 | 按「老年/青年/少年 × 男/女」分组的五官描述 |
| 七、体型映射 | 体型 → 英文提示词 |

**改风格示例**（把「唯美艺术型」调得更冷峻）：

```yaml
风格:
  唯美艺术型:
    描述: 清冷疏离的东方美学，克制的华丽，留白与雾气
    气质关键词: [清冷, 疏离, 空灵, 矜贵, 克制, 出尘]
    偏好颜色: [白色, 黑色, 藏青色, 紫色]
    姿势: 正面站立，肩背挺直，目光平视，衣摆微垂
    光影: 冷调侧逆光，薄雾散射，低饱和，局部高光
    细节: 极高，面料暗纹与刺绣清晰，配饰精简
```

操作要点：

- 只改 YAML 代码块内的**内容**，保持缩进（空格）与 `-`、`:` 结构
- 新增风格：复制一段现有风格，改名字和字段即可；风格名会成为导出文件名的一部分，避免特殊符号
- 保存后服务端按文件修改时间**热加载**，下一次生成自动生效，无需重启
- 也可以在前端「工程」页在线编辑、校验、保存、恢复默认（旧配置自动备份）
- 通过前端「自定义风格」用自然语言生成的新风格，会写入 `output/config/custom_styles.json`

### 7.2 画风层：替换 LoRA（最常改的地方）

**只换画风（例如从古风二次元换成写实电影感），优先换 LoRA。**

1. 把新的 LoRA 放进 ComfyUI：

   ```
   ComfyUI/models/loras/你的LoRA文件名.safetensors
   ```

2. 修改文生图工作流 `FLUX(文生图）-短剧项目-API-agent(test).json` 中的 **LoraLoader 节点（节点 id = 10）**：

   | 字段 | 当前值 | 说明 |
   |------|--------|------|
   | `lora_name` | `F.1-古风小说推文（堪比niji）_v2.0.safetensors` | 换成新 LoRA 文件名 |
   | `strength_model` | `0.8` | 画风强度，越大越像 LoRA，过大易崩坏 |
   | `strength_clip` | `1.0` | 文本侧强度，通常与模型强度接近 |

3. 修图工作流也有一个 LoRA：`服装迁移-千问Edit2509图像编辑 (2)-API-agent-test.json` 的 **LoraLoaderModelOnly 节点（节点 id = 34）**，当前 `strength_model = 0.4`，可按需替换。

两种改法：

- **同名覆盖**：新文件改成旧文件名，直接覆盖 `models/loras/` 里的文件 → 不用改任何 JSON
- **换名**：修改工作流 JSON 的 `lora_name`（推荐在 ComfyUI 界面里改好，再用「导出 API 格式」覆盖根目录的 `-API` 文件）

### 7.3 基座层：替换主模型

需要换 FLUX 版本或其他底座时，改下面这些节点（文件名必须与 `ComfyUI/models/` 下一致）：

| 工作流节点 | 节点 id | 当前文件 | 模型目录 |
|------------|---------|----------|----------|
| `UNETLoader` | 5 | `flux1-dev.safetensors` | `models/unet/` |
| `DualCLIPLoader` | 4 | `clip_l.safetensors` + `t5xxl_fp16.safetensors` | `models/clip/` |
| `VAELoader` | 2 | `ae.safetensors` | `models/vae/` |

修图工作流对应：

| 节点 | 节点 id | 当前文件 |
|------|---------|----------|
| `UNETLoader` | 1 | `qwen_image_edit_2509_fp8_e4m3fn.safetensors` |
| `CLIPLoader` | 2 | `qwen_2.5_vl_7b_fp8_scaled.safetensors` |
| `VAELoader` | 3 | `qwen_image_vae.safetensors` |

> 换基座模型往往意味着采样参数、CLIP 类型也要一起调整，建议先在 ComfyUI 界面里调通、出图满意，再导出 API 格式替换仓库里的工作流。

### 7.4 工作流与节点 ID 的对应关系

后端不是「打开工作流文件自由解析」，而是通过固定节点 ID 注入参数。节点 ID 定义在 `backend/config.py`：

```python
T2I_NODES = {
    "text": "17",            # 正向提示词（Text Multiline）
    "flux_guidance": "3",    # FluxGuidance
    "clip_encode": "8",      # CLIPTextEncodeFlux
    "negative": "7",         # 负向提示词
    "empty_latent": "12",    # 宽高
    "save_image": "11",
    "ksampler": "6",         # seed
}
```

因此：

- 如果你新增/删除/重排节点，导致这些 ID 变化，必须同步修改 `config.py`（或改回原 ID）
- 工作流必须是 **API 格式**（`-API` 文件），UI 格式无法直接提交给 ComfyUI 的 `/prompt` 接口
- 出图尺寸、引导强度也在 `config.py`：`T2I_WIDTH=720`、`T2I_HEIGHT=1280`、`T2I_GUIDANCE=8.0`、`T2I_CLIP_GUIDANCE=3.5`

### 7.5 推荐操作顺序（换风格时）

1. 先在 ComfyUI 里手动跑通新 LoRA / 新模型，确认画风符合预期
2. 回到 `prompt_engineering.md`，调整「五、风格预设」与「一、全局设定」里的背景、质量词
3. 如果需要新的身份体系，再改「三、身份设定」与「四、特殊特征」
4. 重新生成 3~5 个角色试跑，确认提示词与画面一致
5. 满意后再批量出图；不满意的图片可用「修图」或单张重出

---

## 8. 配置项

所有配置均可通过环境变量覆盖（`backend/config.py`）。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama 地址 |
| `OLLAMA_MODEL` | `qwen2.5:14b` | 提示词生成主模型 |
| `OLLAMA_FALLBACK_MODELS` | `qwen2.5:14b,qwen2.5:7b,qwen3:32b` | 主模型不可用时的降级顺序 |
| `COMFYUI_URL` | `http://127.0.0.1:8188` | ComfyUI 地址 |
| `DASHSCOPE_API_KEY` | 空 | 百炼 API Key，仅质量评估需要 |
| `DASHSCOPE_VL_MODEL` | `qwen-vl-plus` | 视觉评分模型 |
| `EVALUATE_THRESHOLD` | `70` | 及格分数线，低于则标记 `needs_regen` |
| `EVALUATE_BATCH_LIMIT` | `20` | 单次批量评估上限 |
| `SERVER_HOST` / `SERVER_PORT` | `0.0.0.0` / `8000` | Web 服务监听地址 |
| `MAX_CONCURRENT_TASKS` | `1` | GPU 任务并发数，建议保持 1 |
| `RATE_LIMIT_PER_MINUTE` | `30` | 每分钟请求上限 |
| `RATE_LIMIT_GENERATE_PER_HOUR` | `20` | 每小时出图任务上限 |
| `LLM_MAX_RETRIES` / `COMFYUI_MAX_RETRIES` | `2` | 失败重试次数 |
| `T2I_WORKFLOW` | 仓库根的 FLUX API 工作流 | 文生图工作流路径 |
| `EDIT_WORKFLOW` | 仓库根的千问 Edit API 工作流 | 修图工作流路径 |
| `OUTPUT_DIR` | `output` | 产物目录 |

---

## 9. API 摘要

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查（Ollama / ComfyUI） |
| GET | `/api/options` | 可用风格、身份、模型（含自定义风格） |
| POST | `/api/tasks` | 提交异步任务，返回 `task_id` |
| GET | `/api/tasks/{id}` | 查询任务状态与进度 |
| WS | `/ws/tasks` | 实时进度推送 |
| GET | `/api/prompts/list` | 提示词文件列表 |
| GET | `/api/prompts/characters?file=` | 指定文件的角色列表 |
| POST | `/api/evaluate` | 剧照 5 维质量评分 |
| GET | `/api/list_images` | 画廊图片（stills + edited） |
| POST | `/api/export` / `/api/export/by_images` | 导出打标 Excel + 入库 SQL |
| GET/PUT | `/api/prompt-guide` | 读取 / 保存提示词工程配置 |
| POST | `/api/prompt-guide/validate` | 校验 YAML 配置 |
| POST | `/api/prompt-guide/reload` | 手动热加载配置 |
| POST | `/api/prompt-guide/restore` | 恢复默认配置（自动备份） |

v2.2 起已移除登录注册，所有 API 匿名可访问，仅保留 IP 级速率限制。部署到公网前请自行加反向代理认证并收紧 CORS。

---

## 10. 常见问题

**Q：拆开项目后提示 `Cannot find module` / 页面白屏？**  
生产模式要先 `cd frontend && npm run build`，确认 `backend/static/index.html` 存在；开发模式请用 `npm run dev` 访问 5173。

**Q：ComfyUI 返回 400 / `node not found`？**  
工作流里的节点 ID 与 `config.py` 不一致，或缺少自定义节点（如 `TextEncodeQwenImageEditPlus_lrzjason`）。先在 ComfyUI 里打开工作流补齐节点，再导出 API 格式。

**Q：ComfyUI 报模型不存在？**  
文件名必须与工作流 `widgets_values` / `inputs` 中的名字完全一致，包括中文 LoRA 名。确认放在 `models/unet`、`models/clip`、`models/vae`、`models/loras` 对应目录。

**Q：出图很慢或显存溢出？**  
保持 `MAX_CONCURRENT_TASKS=1`；确认 Ollama 没有把模型塞进 CPU（会明显变慢）。FLUX 与千问 Edit 不要并行。

**Q：改了 `.env` 没生效？**  
本项目不会自动加载 `.env`，请按 4.4 设置操作系统环境变量，或在启动脚本里显式加载。

**Q：质量评估报 API Key 错误？**  
配置 `DASHSCOPE_API_KEY` 并重启服务；未配置不影响提示词与出图。

**Q：生成的图片在哪里？**  
`output/stills/<task_id>/`、`output/edited/<task_id>/`、`output/export/`。`output/` 已被 `.gitignore` 忽略，不会进入仓库。

**Q：想清空所有生成结果？**  
停止服务后删除 `output/` 目录即可，下次启动会自动重建所需子目录。

---

## 说明

- 本项目面向本地 / 内网批量生产，默认无登录态，请勿直接暴露到公网
- 使用的 FLUX、Qwen-Image-Edit 及第三方 LoRA 均遵循其各自的开源 / 商业许可，请在使用前确认授权范围
- 角色设定与生成的剧照仅用于个人学习与创作，请勿用于侵权或违法用途
