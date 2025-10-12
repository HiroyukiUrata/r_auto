import logging
from app.core.config_manager import get_config
from app.tasks.rakuten_api_procure import procure_from_rakuten_api
from app.tasks.rakuten_search_procure import search_and_procure_from_rakuten

def run_procurement_flow(count: int = 5):
    """
    設定ファイルに基づいて、適切な商品調達タスクを実行する。
    スケジュール実行の起点となる関数。
    :param count: 調達する商品のおおよその件数
    """
    config = get_config()
    procurement_method = config.get("procurement_method", "search")  # デフォルトは検索
    
    logging.info(f"商品調達フローを開始します。選択された方法: {procurement_method}")
    if procurement_method == "api":
        procure_from_rakuten_api(count=count)
    else: # "search" or default
        search_and_procure_from_rakuten(count=count)