# ベースイメージ
FROM python:3.11-slim

# 作業ディレクトリ
WORKDIR /workspace/app

# システム依存パッケージ（必要に応じて）
RUN apt-get update && \
    apt-get install -y curl wget git && \
    rm -rf /var/lib/apt/lists/*

# Pythonパッケージコピーとインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# コンテナ起動時に bash
CMD ["bash"]
