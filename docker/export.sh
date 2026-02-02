#!/bin/bash

# 检查是否提供了镜像名称
if [ $# -eq 0 ]; then
    echo "用法: $0 <镜像名称1> [镜像名称2] ... [镜像名称N]"
    echo "示例: $0 ubuntu:20.04 hnby/fs-ai-agent:20250906"
    exit 1
fi

# 遍历所有输入的镜像名称
for IMAGE_NAME in "$@"; do
    echo "====================================="
    echo "开始处理镜像: $IMAGE_NAME"
    
    # 先替换斜杠为下划线，再替换冒号为下划线
    SAFE_IMAGE_NAME=$(echo "$IMAGE_NAME" | tr '/' '_' | tr ':' '_')
    IMG_FILE="${SAFE_IMAGE_NAME}.img"
    TAR_FILE="${IMG_FILE}.tar.gz"

    echo "使用安全文件名: $SAFE_IMAGE_NAME"

    # 检查镜像是否存在
    if ! docker image inspect "$IMAGE_NAME" &> /dev/null; then
        echo "错误: 镜像 '$IMAGE_NAME' 不存在，跳过处理"
        continue
    fi

    # 清理可能存在的文件
    rm -f "$IMG_FILE" "$TAR_FILE"

    # 导出镜像
    echo "导出镜像 '$IMAGE_NAME' 到 '$IMG_FILE'..."
    if docker save -o "$IMG_FILE" "$IMAGE_NAME"; then
        echo "镜像导出成功"
    else
        echo "错误: 镜像 '$IMAGE_NAME' 导出失败，跳过压缩步骤"
        continue
    fi

    # 压缩文件（强制本地模式）
    echo "压缩 '$IMG_FILE' 到 '$TAR_FILE'..."
    if tar -czvf "$TAR_FILE" --force-local "$IMG_FILE"; then
        echo "压缩成功"
    else
        echo "错误: '$IMG_FILE' 压缩失败"
        continue
    fi

    echo "镜像 '$IMAGE_NAME' 处理完成，生成文件:"
    echo "- $IMG_FILE"
    echo "- $TAR_FILE"
    echo "====================================="
    echo
done

echo "所有镜像处理完毕"
exit 0
