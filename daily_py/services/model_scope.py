# import os
# # 第一步：强制使用 huggingface 国内镜像（关键）
# os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
#
# from huggingface_hub import snapshot_download
#
# # 下载配置
# snapshot_download(
#     repo_id="Qwen/Qwen3-ASR-0.6B",
#     local_dir=r"D:\my_models",
#     # 增加 3 个关键参数，解决卡住/中断/超时
#     resume_download=True,        # 断点续传
#     max_workers=8,               # 多线程加速
#     etag_timeout=30,             # 超时时间延长
# )


from modelscope import snapshot_download

# 直接下载，速度飞快
snapshot_download(
    model_id="qwen/Qwen3-ASR-0.6B",
    local_dir=r"D:\my_models\Qwen3-ASR-0.6B",
    revision="master",
)