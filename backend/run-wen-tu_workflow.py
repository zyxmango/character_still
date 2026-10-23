#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
适配FLUX文生图工作流的批量生成脚本（最终版）
输入：JSON文件（每个"序号"下的"完整英文描述词"）
输出：/root/auto_comfyui/output_wen-tu/序号.png（直接放根目录，无嵌套文件夹）
"""
import json
import time
import urllib.request
import argparse
import traceback
from pathlib import Path
from urllib.parse import quote
from copy import deepcopy

# ==================== 配置区（最终版） ====================
COMFY_SERVER      = "http://127.0.0.1:8188"
WORKFLOW_JSON     = "/root/auto_Text-to-Image_character/workfiows/文生图flux-api.json"  # 新FLUX工作流路径
INPUT_JSON_FILE   = "/root/auto_Text-to-Image_character/generated_prompts_唯美艺术型_20260407_153017.json"  # 输入描述词JSON
OUTPUT_DIR        = Path("/root/auto_Text-to-Image_character/output/test9")  # 直接输出到该根目录
TEXT_INPUT_NODE   = "112"  # 核心文本输入节点（ttN text）
FLUX_GUIDANCE_NODE= "49"   # FluxGuidance节点ID
CLIP_ENCODE_NODE  = "63"   # CLIPTextEncodeFlux节点ID
SAVE_IMAGE_NODE   = "48"   # 保存图片节点ID（SaveImage）
POLL_INTERVAL     = 3      # FLUX生成慢，加大轮询间隔（秒）
# FLUX特有配置
FLUX_GUIDANCE_VAL = 8.0    # FluxGuidance节点(49)的guidance参数
CLIP_GUIDANCE_VAL = 3.5    # CLIPTextEncodeFlux节点(63)的guidance参数
# ===============================================

def post_json(url: str, data: dict):
    """POST请求发送JSON数据（带超时处理+详细错误日志）"""
    try:
        json_data = json.dumps(data, ensure_ascii=False)
        req = urllib.request.Request(
            url,
            data=json_data.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_detail = e.read().decode('utf-8') if e.fp else "无详细信息"
        raise Exception(f"POST请求失败 [{e.code}]：{e.reason}，详情：{error_detail}")
    except urllib.error.URLError as e:
        raise Exception(f"POST请求失败：{e.reason}")
    except Exception as e:
        raise Exception(f"POST请求异常：{str(e)}")

def get_json(url: str):
    """GET请求获取JSON数据（带超时处理）"""
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        raise Exception(f"GET请求失败：{e.reason}")
    except Exception as e:
        raise Exception(f"GET请求异常：{str(e)}")

def download_file(url: str, dst: Path):
    """下载图片文件到指定路径（带异常处理）"""
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)  # 确保根目录存在
        urllib.request.urlretrieve(url, dst)
        print(f"[+] 已保存 => {dst}")
    except Exception as e:
        print(f"[-] 下载图片失败 {dst}：{e}")

# -------------------- 参数解析 --------------------
parser = argparse.ArgumentParser()
parser.add_argument("--test-ids", type=str, default="", 
                    help='指定测试的序号，例： "170,171"')
args = parser.parse_args()

# -------------------- 加载输入数据 --------------------
try:
    with open(INPUT_JSON_FILE, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
    
    # 提取Sheet1下的列表，并转换为 {序号: 完整英文描述词} 的字典
    input_data = {}
    sheet_list = raw_data.get("Sheet1", [])
    
    for item_idx, item in enumerate(sheet_list, 1):
        # 1. 校验item是否为字典
        if not isinstance(item, dict):
            print(f"[警告] 第{item_idx}个条目不是字典，跳过：{item}")
            continue
        
        # 2. 提取并校验序号
        seq_val = item.get("序号")
        if seq_val is None or seq_val == "":
            print(f"[警告] 第{item_idx}个条目序号为空，跳过")
            continue
        
        # 3. 转换序号为字符串（兼容数字/字符串类型）
        try:
            seq_num = int(float(seq_val)) if not isinstance(seq_val, str) else seq_val.strip()
            seq_id = str(seq_num)
        except (ValueError, TypeError):
            print(f"[警告] 第{item_idx}个条目序号无效（{seq_val}），跳过")
            continue
        
        # 4. 提取并校验描述词
        prompt_text = item.get("完整英文描述词", "").strip()
        if not prompt_text:
            print(f"[警告] 序号{seq_id}的描述词为空，跳过")
            continue
        
        input_data[seq_id] = prompt_text

    # 验证数据提取结果
    print("=== 数据提取验证 ===")
    print(f"提取到有效序号数：{len(input_data)}")
    print(f"序号列表：{list(input_data.keys())[:10]}..." if len(input_data) > 10 else list(input_data.keys()))
    if input_data:
        first_seq = list(input_data.keys())[0]
        print(f"第一个序号({first_seq})描述词预览：{input_data[first_seq][:100]}...")
    print("====================\n")

    if not input_data:
        print("[-] 未提取到有效数据，程序退出")
        exit(1)

except FileNotFoundError:
    print(f"[-] 输入文件不存在：{INPUT_JSON_FILE}")
    exit(1)
except json.JSONDecodeError as e:
    print(f"[-] JSON格式错误：{INPUT_JSON_FILE}，错误：{e}")
    exit(1)
except Exception as e:
    print(f"[-] 加载输入数据时发生异常：{e}")
    exit(1)

# -------------------- 筛选待处理序号 --------------------
if args.test_ids:
    test_ids = [id.strip() for id in args.test_ids.split(",") if id.strip()]
    process_ids = [id for id in test_ids if id in input_data]
    if not process_ids:
        print(f"[-] 指定的测试序号{test_ids}未在数据中找到，程序退出")
        exit(1)
    print(f"[+] 测试模式 - 待处理序号：{process_ids}")
else:
    process_ids = sorted(list(input_data.keys()), key=lambda x: int(x) if x.isdigit() else x)
    print(f"[+] 批量模式 - 待处理序号数：{len(process_ids)}")

# -------------------- 加载基础工作流 --------------------
try:
    with open(WORKFLOW_JSON, "r", encoding="utf-8") as f:
        base_workflow = json.load(f)
    print(f"[+] 成功加载工作流：{WORKFLOW_JSON}")
    
    # 验证关键节点是否存在
    critical_nodes = [TEXT_INPUT_NODE, FLUX_GUIDANCE_NODE, CLIP_ENCODE_NODE, SAVE_IMAGE_NODE]
    missing_nodes = [n for n in critical_nodes if n not in base_workflow]
    if missing_nodes:
        print(f"[-] 错误：工作流中缺少关键节点 {missing_nodes}")
        exit(1)

except FileNotFoundError:
    print(f"[-] 工作流文件不存在：{WORKFLOW_JSON}")
    exit(1)
except json.JSONDecodeError as e:
    print(f"[-] 工作流JSON格式错误：{WORKFLOW_JSON}，错误：{e}")
    exit(1)
except Exception as e:
    print(f"[-] 加载工作流时发生异常：{e}")
    exit(1)

# -------------------- 批量处理每个序号 --------------------
total_success = 0
total_failed = 0

for idx, seq_id in enumerate(process_ids, 1):
    prompt_text = input_data[seq_id]
    print(f"\n===== 处理进度：{idx}/{len(process_ids)} 序号：{seq_id} =====")
    print(f"[+] 描述词：{prompt_text[:80]}..." if len(prompt_text) > 80 else f"[+] 描述词：{prompt_text}")

    # 深拷贝基础工作流
    try:
        workflow = deepcopy(base_workflow)
    except Exception as e:
        print(f"[-] 拷贝工作流失败：{e}，跳过当前序号")
        total_failed += 1
        continue

    # ========== 适配新工作流的节点配置 ==========
    try:
        # 1. 更新核心文本输入节点(112) - ttN text
        text_node = workflow[TEXT_INPUT_NODE]
        if "inputs" not in text_node:
            text_node["inputs"] = {}
        text_node["inputs"]["text"] = prompt_text  # 设置正向描述词
        print(f"[+] 已更新文本节点({TEXT_INPUT_NODE})：{prompt_text[:50]}...")

        # 2. 更新FluxGuidance节点(49)的guidance参数
        guidance_node = workflow[FLUX_GUIDANCE_NODE]
        if "inputs" not in guidance_node:
            guidance_node["inputs"] = {}
        guidance_node["inputs"]["guidance"] = FLUX_GUIDANCE_VAL
        print(f"[+] 已更新Flux引导节点({FLUX_GUIDANCE_NODE})：guidance={FLUX_GUIDANCE_VAL}")

        # 3. 更新CLIPTextEncodeFlux节点(63)的guidance参数
        clip_node = workflow[CLIP_ENCODE_NODE]
        if "inputs" not in clip_node:
            clip_node["inputs"] = {}
        clip_node["inputs"]["guidance"] = CLIP_GUIDANCE_VAL
        print(f"[+] 已更新CLIP编码节点({CLIP_ENCODE_NODE})：guidance={CLIP_GUIDANCE_VAL}")
        
    except Exception as e:
        print(f"[-] 修改工作流节点失败：{e}")
        traceback.print_exc()
        total_failed += 1
        continue

    # 提交任务到ComfyUI
    try:
        print("[+] 提交任务到ComfyUI...")
        
        # 构建标准的ComfyUI请求体
        request_data = {
            "prompt": workflow,
            "client_id": f"flux_batch_{seq_id}_{int(time.time())}",
            "extra_data": {"skip_image_validate": False}
        }
        
        prompt_resp = post_json(f"{COMFY_SERVER}/prompt", request_data)
        prompt_id = prompt_resp.get("prompt_id")
        
        if not prompt_id:
            print(f"[-] 未获取到prompt_id，响应内容：{prompt_resp}")
            total_failed += 1
            continue
            
        print(f"[+] 任务提交成功，prompt_id：{prompt_id}")
        
    except Exception as e:
        print(f"[-] 提交任务失败：{e}")
        traceback.print_exc()
        total_failed += 1
        continue

    # 轮询任务状态
    task_completed = False
    retry_count = 0
    max_retry = 400  # 最大轮询次数（20分钟）
    
    while retry_count < max_retry:
        try:
            history_url = f"{COMFY_SERVER}/history/{prompt_id}"
            history = get_json(history_url)
            
            if history and prompt_id in history:
                # 任务完成，处理图片下载
                task_data = history[prompt_id]
                
                # 检查任务是否成功
                if not task_data.get("status", {}).get("completed", False):
                    error_info = task_data.get("status", {}).get("errors", "未知错误")
                    print(f"[-] 序号{seq_id}任务执行失败：{error_info}")
                    total_failed += 1
                    task_completed = True
                    break
                
                outputs = task_data.get("outputs", {})
                save_output = outputs.get(SAVE_IMAGE_NODE, {})
                images = save_output.get("images", [])
                
                if images:
                    # 核心修改：直接输出到根目录，无嵌套文件夹，文件名=序号.png
                    img_info = images[0]  # 只取第一张图
                    img_url = (
                        f"{COMFY_SERVER}/view?"
                        f"filename={quote(str(img_info['filename']))}"
                        f"&subfolder={quote(str(img_info['subfolder']))}"
                        f"&type={quote(str(img_info['type']))}"
                    )
                    
                    # 最终输出路径：/root/auto_comfyui/output_wen-tu/序号.png
                    img_path = OUTPUT_DIR / f"{seq_id}.png"
                    download_file(img_url, img_path)
                    
                    total_success += 1
                    print(f"[+] 序号{seq_id}处理完成，保存1张图片")
                else:
                    print(f"[-] 序号{seq_id}无图片输出，检查节点{SAVE_IMAGE_NODE}配置")
                    total_failed += 1
                
                # 删除任务历史（释放内存）
                try:
                    post_json(f"{COMFY_SERVER}/history", {"delete": [prompt_id]})
                    print(f"[+] 已清理任务历史")
                except Exception as e:
                    print(f"[-] 删除历史记录失败：{e}")
                
                task_completed = True
                break
                
            else:
                retry_count += 1
                if retry_count % 20 == 0:
                    print(f"[*] 等待任务完成... ({retry_count}/{max_retry})")
                time.sleep(POLL_INTERVAL)
                
        except Exception as e:
            retry_count += 1
            print(f"[-] 查询任务状态失败：{e}，重试({retry_count}/{max_retry})")
            time.sleep(POLL_INTERVAL)
    
    if not task_completed:
        print(f"[-] 序号{seq_id}任务超时未完成（超时时间：{max_retry*POLL_INTERVAL}秒）")
        total_failed += 1

# -------------------- 输出最终统计 --------------------
print("\n" + "="*50)
print("处理完成统计")
print("="*50)
print(f"总处理序号数：{len(process_ids)}")
print(f"成功数：{total_success}")
print(f"失败数：{total_failed}")
print(f"成功率：{total_success/len(process_ids)*100:.1f}%" if process_ids else "N/A")
print(f"输出目录：{OUTPUT_DIR.absolute()}")
print("="*50)
