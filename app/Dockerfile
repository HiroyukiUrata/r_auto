# ベースイメージ
FROM python:3.11-slim

# 作業ディレクトリ
WORKDIR /workspace

# VNCとブラウザ表示に必要なパッケージをインストール
# --no-install-recommends で不要な推奨パッケージをスキップし、
# 最後に apt-get clean と /var/lib/apt/lists/* の削除を行うことでイメージサイズを削減します。
RUN apt-get update && apt-get install -y --no-install-recommends \
    x11vnc \
    xvfb \
    xauth \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Pythonパッケージコピーとインストール
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Playwrightのブラウザをインストール
RUN playwright install --with-deps

# Copy and set permissions for the entrypoint script
COPY app/entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# デフォルトのコマンド。docker-compose.ymlのcommandで上書きされる。
CMD ["python", "-m", "app.main"] 