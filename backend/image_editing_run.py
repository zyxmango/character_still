#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每张输入图 → output/上一级文件夹名/原文件名.png
保持输入目录结构最后一级，不再为每张图单独建文件夹
输入是文件夹
"""
import json, time, urllib.request, argparse
from pathlib import Path
from urllib.parse import quote

# ==================== 配置区 ====================
COMFY_SERVER      = "http://127.0.0.1:8188"
WORKFLOW_JSON     = "/root/auto_Text-to-Image_character/image_editing/服装迁移-千问Edit2509图像编辑(API)4.json"
INPUT_FOLDERS     = "/root/auto_Text-to-Image_character/editing_output/test9_edit"
OUTPUT_DIR        = Path("/root/auto_Text-to-Image_character/editing_output/test9_edit2")
LOAD_IMAGE_NODE   = "15"
SAVE_IMAGE_NODE   = "22"
POLL_INTERVAL     = 1
# ===============================================

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".jfif"}

def post_json(url: str, data: dict):
    req = urllib.request.Request(url, data=json.dumps(data).encode(),
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def get_json(url: str):
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())

def download_file(url: str, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dst)
    print(f"[+] 已保存 => {dst}")

def upload_image(file_path: Path) -> str:
    boundary = "----ComfyUIUploadBoundary"
    body = (f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{file_path.name}"\r\n'
            f"Content-Type: image/jpeg\r\n\r\n").encode() \
           + file_path.read_bytes() \
           + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{COMFY_SERVER}/upload/image", data=body,
                  headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())["name"]

# -------------------- 参数解析 --------------------
parser = argparse.ArgumentParser()
parser.add_argument("--test-images", type=str, default="", help='例： "img1.jpg,img2.png"')
args = parser.parse_args()

# -------------------- 主流程 --------------------
with open(WORKFLOW_JSON, "r", encoding="utf-8") as f:
    base_workflow = json.load(f)

INPUT_DIRS = [Path(p.strip()) for p in INPUT_FOLDERS.split(",")]
all_imgs   = sorted([p for folder in INPUT_DIRS for p in folder.rglob("*") if p.suffix.lower() in IMG_EXT])

if args.test_images:
    want_set = {name.strip() for name in args.test_images.split(",") if name.strip()}
    img_files = [p for p in all_imgs if f"{p.parent.name}/{p.name}" in want_set]
    if not img_files:
        print("[-] 未找到指定的测试图片，程序退出")
        exit()
    print(f"[+] 指定测试图片：{[p.name for p in img_files]}")
else:
    img_files = all_imgs
    if not img_files:
        print("[-] input/ 里没有可处理的图片，程序退出")
        exit()
    print(f"[+] 共发现 {len(img_files)} 张图片，开始批量处理...")

for idx, img_path in enumerate(img_files, 1):
    print(f"\n===== 第 {idx}/{len(img_files)} 张：{img_path.name} =====")
    uploaded_name = upload_image(img_path)
    print(f"[+] 已上传 => {uploaded_name}")

    workflow = json.loads(json.dumps(base_workflow))
    workflow[LOAD_IMAGE_NODE]["inputs"]["image"] = uploaded_name
    workflow[SAVE_IMAGE_NODE]["inputs"]["filename_prefix"] = "img"

    prompt_id = post_json(f"{COMFY_SERVER}/prompt", {"prompt": workflow})["prompt_id"]
    print(f"[+] 任务已提交，prompt_id = {prompt_id}")

    while True:
        history = get_json(f"{COMFY_SERVER}/history/{prompt_id}")
        if history:
            print("[+] 任务完成，开始下载 SaveImage 图片...")
            save_node = history[prompt_id]["outputs"].get(SAVE_IMAGE_NODE)
            if save_node and "images" in save_node:
                # 只取上一级文件夹名+原文件名
                parent_name = img_path.parent.name   # 光头
                file_stem   = img_path.stem          # 001
                out_dir     = OUTPUT_DIR / parent_name
                for i, img in enumerate(save_node["images"]):
                    new_name = f"{file_stem}.png" if i == 0 else f"{file_stem}_{i+1:03d}.png"
                    url = (f"{COMFY_SERVER}/view?"
                           f"filename={quote(img['filename'])}"
                           f"&subfolder={quote(img['subfolder'])}"
                           f"&type={quote(img['type'])}")
                    download_file(url, out_dir / new_name)
            else:
                print("[-] 未找到 SaveImage 节点，无图可下")
            # 删除历史记录
            req = urllib.request.Request(f"{COMFY_SERVER}/history",
                             data=json.dumps({"delete": [prompt_id]}).encode(),
                             headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req).read()
            break
        time.sleep(POLL_INTERVAL)

print("\n[+] 全部完成！")
