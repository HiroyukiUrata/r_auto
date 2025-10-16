# ベースイメージq
FROM python:3.11-slim

# 作業ディレクトリ
WORKDIR /workspace

# VNCとブラウザ表示に必要なパッケージをインストール
RUN apt-get update && apt-get install -y --no-install-recommends \
    x11vnc \
    xvfb \
    xauth

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
