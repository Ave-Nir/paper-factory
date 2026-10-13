"""
图片生成模块 —— 调用生图模型生成高质量学术流程图
"""
import base64
import os
import sys
import time
import requests
from datetime import datetime
from pathlib import Path
from openai import OpenAI
from openai import APIConnectionError, APIError, InternalServerError, APITimeoutError

# 确保项目根目录在path中
_project_root = str(Path(__file__).resolve().parents[3])  # paper-factory 根目录
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# 从统一配置中心导入API配置
from api_config import IMAGE_API

# ========== 配置常量 ==========
DEFAULT_IMAGE_SIZE = "1792x1024"              # 默认图片尺寸
DEFAULT_IMAGE_QUALITY = "high"                # 默认图片质量
DEFAULT_IMAGE_STYLE = "natural"               # 默认图片风格
NON_RETRYABLE_STATUS_CODES = [400, 401, 403, 429]  # 不可重试的HTTP状态码


class ImageGenerator:
    def __init__(self, api_key: str = None, base_url: str = None,
                 model: str = None, timeout: int = 180, max_retries: int = 3, 
                 retry_delay: int = 30, total_timeout: int = None):
        """
        初始化图片生成器
        
        :param api_key: API密钥（默认从api_config读取）
        :param base_url: API端点（默认从api_config读取）
        :param model: 模型名称（默认从api_config读取）
        :param timeout: 单次请求超时时间（秒）
        :param max_retries: 最大重试次数
        :param retry_delay: 重试间隔（秒）
        :param total_timeout: 总超时时间（秒，包括所有重试），None表示不限制
        """
        self.client = OpenAI(
            base_url=base_url or IMAGE_API.base_url,
            api_key=api_key or IMAGE_API.api_key,
            timeout=timeout,
        )
        self.model = model or IMAGE_API.model
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.total_timeout = total_timeout

    def generate_image(self, prompt: str, output_path: str = None,
                      timeout: int = None, max_retries: int = None,
                      total_timeout: int = None, model: str = None,
                      size: str = None) -> str:
        """
        调用图片生成模型（带超时和重试机制）
        
        :param prompt: 绘图提示词
        :param output_path: 输出路径（可选，默认自动生成）
        :param timeout: 单次请求超时时间（秒），覆盖默认值
        :param max_retries: 最大重试次数，覆盖默认值
        :param total_timeout: 总超时时间（秒，覆盖默认值）
        :param model: 模型名称，覆盖默认值
        :param size: 图片尺寸，如 "1792x1024"
        :return: 生成的图片路径
        """
        effective_timeout = timeout or self.timeout
        effective_retries = max_retries or self.max_retries
        effective_total_timeout = total_timeout or self.total_timeout
        effective_model = model or self.model
        effective_size = size or DEFAULT_IMAGE_SIZE
        
        print(f"正在调用 {effective_model} 生成图片...")
        print(f"尺寸: {effective_size}")
        print(f"提示词长度: {len(prompt)} 字符")
        print(f"超时设置: 单次 {effective_timeout}秒, 最大重试 {effective_retries}次, "
              f"总超时 {'无限制' if effective_total_timeout is None else f'{effective_total_timeout}秒'}")

        last_error = None
        start_time = time.time()
        
        for attempt in range(effective_retries):
            elapsed = time.time() - start_time
            
            if effective_total_timeout is not None and elapsed >= effective_total_timeout:
                print(f"\n⏰ 总超时时间已达 {effective_total_timeout}秒，退出重试")
                raise TimeoutError(f"图片生成总超时: {effective_total_timeout}秒")
            
            remaining = effective_total_timeout - elapsed if effective_total_timeout else None
            print(f"  第 {attempt + 1}/{effective_retries} 次尝试 "
                  f"(已耗时: {int(elapsed)}秒, "
                  f"剩余: {'无限制' if remaining is None else f'{int(remaining)}秒'})...")
            
            try:
                response = self.client.images.generate(
                    model=effective_model,
                    prompt=prompt,
                    size=effective_size,
                    n=1,
                )

                img_data = None
                img_obj = response.data[0]
                
                if img_obj.b64_json:
                    img_data = base64.b64decode(img_obj.b64_json)
                elif img_obj.url:
                    print(f"  下载图片: {img_obj.url[:80]}...")
                    download_resp = requests.get(img_obj.url, timeout=120)
                    download_resp.raise_for_status()
                    img_data = download_resp.content
                
                if img_data:
                    if not output_path:
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        output_path = f"output/diagram_{timestamp}.png"

                    output_path = Path(output_path)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(img_data)

                    total_elapsed = int(time.time() - start_time)
                    print(f"✅ 图片已保存: {output_path} (耗时: {total_elapsed}秒)")
                    return str(output_path)

                print(f"  第 {attempt + 1} 次失败: 返回数据为空")
                last_error = RuntimeError("生成失败: 返回数据为空")

            except APITimeoutError as e:
                print(f"  第 {attempt + 1} 次失败: 单次请求超时 ({effective_timeout}秒)")
                last_error = e

            except (APIConnectionError, InternalServerError) as e:
                print(f"  第 {attempt + 1} 次失败: 连接/服务器错误 - {type(e).__name__}")
                last_error = e

            except APIError as e:
                print(f"  第 {attempt + 1} 次失败: API错误 - {e}")
                if e.status_code in NON_RETRYABLE_STATUS_CODES:
                    print(f"  非可重试错误({e.status_code})，直接退出")
                    raise e
                last_error = e

            except Exception as e:
                print(f"  第 {attempt + 1} 次失败: {type(e).__name__} - {e}")
                last_error = e

            if attempt < effective_retries - 1:
                print(f"  {self.retry_delay}秒后重试...")
                time.sleep(self.retry_delay)

        total_elapsed = int(time.time() - start_time)
        print(f"\n❌ 图片生成失败，已重试 {effective_retries} 次 (总耗时: {total_elapsed}秒)")
        if last_error:
            raise last_error
        else:
            raise RuntimeError(f"图片生成失败，已重试 {effective_retries} 次")
