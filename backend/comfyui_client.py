# -*- coding: utf-8 -*-
"""
ComfyUI 客户端：文生图(FLUX) + 修图(千问Edit2509)。
节点ID已根据实际工作流核对修正。
"""
import json
import random
import time
import urllib.request
import urllib.error
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote

import config
from logger import get_logger
from retry import retry_with_backoff

logger = get_logger(__name__)


class ComfyUIError(Exception):
    pass


class ComfyUIClient:
    def __init__(self, server_url=None, t2i_workflow=None, edit_workflow=None):
        self.server = (server_url or config.COMFYUI_URL).rstrip("/")
        self.t2i_workflow_path = str(t2i_workflow or config.T2I_WORKFLOW)
        self.edit_workflow_path = str(edit_workflow or config.EDIT_WORKFLOW)

    # ---------------- 基础 HTTP ----------------
    def _post_json(self, url, data):
        try:
            req = urllib.request.Request(
                url, data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = resp.read()
                # 某些 ComfyUI 接口（如 DELETE history）返回空响应体
                if not body:
                    return {}
                return json.loads(body)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore") if e.fp else ""
            raise ComfyUIError(f"POST失败[{e.code}] {e.reason} 详情:{detail}")
        except urllib.error.URLError as e:
            raise ComfyUIError(f"POST连接失败：{e.reason}")

    def _get_json(self, url):
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                return json.loads(resp.read())
        except urllib.error.URLError as e:
            raise ComfyUIError(f"GET失败：{e.reason}")

    def _download(self, url, dst: Path):
        dst.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, dst)

    def _upload_image(self, file_path: Path) -> str:
        """上传图片到 ComfyUI input 目录，返回服务器侧文件名"""
        boundary = "----ComfyUIUploadBoundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{file_path.name}"\r\n'
            f"Content-Type: image/jpeg\r\n\r\n"
        ).encode() + file_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            f"{self.server}/upload/image", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())["name"]

    # ---------------- 任务提交与轮询 ----------------
    @retry_with_backoff(max_retries=config.COMFYUI_MAX_RETRIES, initial_delay=3.0,
                        exceptions=(ComfyUIError, ConnectionError, TimeoutError))
    def _queue_and_wait(self, workflow, client_id="agent"):
        """提交工作流并轮询至完成，返回 outputs 字典"""
        request_data = {
            "prompt": workflow,
            "client_id": f"{client_id}_{int(time.time())}",
            "extra_data": {"skip_image_validate": False},
        }
        resp = self._post_json(f"{self.server}/prompt", request_data)
        prompt_id = resp.get("prompt_id")
        if not prompt_id:
            raise ComfyUIError(f"未获取到prompt_id：{resp}")

        for retry in range(config.POLL_MAX_RETRY):
            history = self._get_json(f"{self.server}/history/{prompt_id}")
            if history and prompt_id in history:
                task_data = history[prompt_id]
                status = task_data.get("status", {})
                # 只有 completed=True 才表示任务真正结束
                if status.get("completed", False):
                    # 检查是否执行出错（status_str 为 error 才是真失败）
                    status_str = status.get("status_str", "")
                    if status_str == "error":
                        messages = status.get("messages", "未知错误")
                        raise ComfyUIError(f"任务执行失败：{messages}")
                    # 成功，清理历史释放内存
                    try:
                        self._post_json(f"{self.server}/history", {"delete": [prompt_id]})
                    except ComfyUIError:
                        pass
                    return task_data.get("outputs", {})
                # completed=False 表示任务还在执行中，继续轮询等待
            time.sleep(config.POLL_INTERVAL)
        raise ComfyUIError(f"任务超时未完成（{config.POLL_MAX_RETRY * config.POLL_INTERVAL}秒）")

    def _save_output_image(self, outputs, save_node_id, dst: Path):
        """从 outputs 中取出 SaveImage 节点的图片并下载到 dst"""
        save_output = outputs.get(save_node_id, {})
        images = save_output.get("images", [])
        if not images:
            raise ComfyUIError(f"节点{save_node_id}无图片输出")
        img = images[0]
        url = (f"{self.server}/view?"
               f"filename={quote(str(img['filename']))}"
               f"&subfolder={quote(str(img.get('subfolder', '')))}"
               f"&type={quote(str(img.get('type', 'output')))}")
        self._download(url, dst)
        return dst

    # ---------------- 文生图 ----------------
    def text_to_image(self, prompt_text, output_path, width=None, height=None,
                      on_log=None):
        """
        单条英文提示词 -> 一张人物剧照。
        prompt_text: 正向提示词（英文）
        output_path: 输出图片路径
        """
        def log(msg):
            if on_log:
                on_log(msg)

        with open(self.t2i_workflow_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)

        n = config.T2I_NODES
        # 1. 正向提示词（Text Multiline 节点）
        workflow[n["text"]].setdefault("inputs", {})["text"] = prompt_text
        log(f"已设置正向提示词(节点{n['text']})")

        # 2. FluxGuidance / CLIPTextEncodeFlux 参数
        workflow[n["flux_guidance"]].setdefault("inputs", {})["guidance"] = config.T2I_GUIDANCE
        workflow[n["clip_encode"]].setdefault("inputs", {})["guidance"] = config.T2I_CLIP_GUIDANCE

        # 3. 尺寸（可选）
        if width and height:
            latent_inputs = workflow[n["empty_latent"]].setdefault("inputs", {})
            latent_inputs["width"] = width
            latent_inputs["height"] = height

        # 4. 保存节点前缀
        workflow[n["save_image"]].setdefault("inputs", {})["filename_prefix"] = "stills"

        # 5. 随机化 seed（避免不同角色脸和发型雷同）
        seed = random.randint(0, 2**53 - 1)
        workflow[n["ksampler"]].setdefault("inputs", {})["seed"] = seed
        log(f"已设置随机 seed: {seed}")

        log("提交文生图任务到 ComfyUI...")
        outputs = self._queue_and_wait(workflow, client_id="t2i")
        dst = Path(output_path)
        self._save_output_image(outputs, n["save_image"], dst)
        log(f"已保存剧照 => {dst}")
        return str(dst)

    # ---------------- 修图 ----------------
    def edit_image(self, image_path, instruction, output_path, on_log=None):
        """
        图片 + 修图指令 -> 修好的图。
        image_path: 待修图片本地路径
        instruction: 修图指令（中文，如"修复手部变形""把鞋子改成平底布鞋"）
        output_path: 输出图片路径
        """
        def log(msg):
            if on_log:
                on_log(msg)

        img_path = Path(image_path)
        if not img_path.exists():
            raise ComfyUIError(f"图片不存在：{image_path}")

        log(f"上传图片 {img_path.name} ...")
        uploaded_name = self._upload_image(img_path)

        with open(self.edit_workflow_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)

        n = config.EDIT_NODES
        # 1. 加载图片节点
        workflow[n["load_image"]].setdefault("inputs", {})["image"] = uploaded_name
        # 2. 修图指令节点（旧代码漏设，现已补上）
        workflow[n["instruction"]].setdefault("inputs", {})["text"] = instruction
        # 3. 保存节点前缀
        workflow[n["save_image"]].setdefault("inputs", {})["filename_prefix"] = "edited"

        log(f"提交修图任务（指令：{instruction}）...")
        outputs = self._queue_and_wait(workflow, client_id="edit")
        dst = Path(output_path)
        self._save_output_image(outputs, n["save_image"], dst)
        log(f"已保存修图结果 => {dst}")
        return str(dst)
